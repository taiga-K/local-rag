"""HTTP API. The body is parsed before a row is written."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import redis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kbindex.config import Settings, load_settings, rebuild_enabled
from kbindex.contract import (
    EXTERNAL_RECORD_ID,
    MAX_BODY_BYTES,
    PushRefusal,
    error_body,
    parse_envelope,
)
from kbindex.db import (
    Database,
    chunk_public_id,
    counts_for,
    delete_chunks_for,
    kb_row,
    lock_record,
    rebuild_bm25,
    record_id_for,
    record_row,
    recover_in_progress,
    replace_graph,
    replace_groups,
    schema_exists,
    schema_row,
)
from kbindex.decide import decide
from kbindex.embed import load_embedder
from kbindex.pipeline import (
    Engine,
    build_pieces,
    groups_of,
    has_indexable_text,
    parent_of,
    prepare,
    texts_of_stored,
    write_payload,
)
from kbindex.qdrant_store import QdrantUnavailable, Vectors
from kbindex.status import apply
from kbindex.stream import ensure_group, publish

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RETRIEVE_KEYS = {
    "query",
    "limit",
    "filters",
    "createdAfter",
    "createdBefore",
    "modifiedAfter",
    "modifiedBefore",
    "maxChunksPerRecord",
    "rewriteQuery",
}
_FILTER_KEYS = {
    "apps",
    "kb",
    "recordGroups",
    "records",
    "recordsExact",
    "entityFilters",
    "allowedApps",
    "allowedRecordGroups",
    "allowedRecords",
    "projectApps",
    "projectRecordGroups",
    "projectRecords",
    "connectionApps",
    "connectionRecordGroups",
    "connectionRecords",
    "selectionApps",
}
_MODEL_CHANGE = (
    "Index settings changed while vectors from the previous fingerprint are still stored. "
    "Search returns 400 INDEX_CONFIG_MISMATCH until those vectors are rebuilt. "
    "One command: POST /api/v1/index/reindex"
)


class KbIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str | None = None
    name: str | None = None


class PropIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=64)
    type: str


class SchemaIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schemaId: str = Field(min_length=1, max_length=300)
    properties: list[PropIn] = Field(default_factory=list, max_length=256)


def admit(content_type: str | None, content_length: str | None, body: bytes) -> None:
    media = (content_type or "").split(";")[0].strip().lower()
    if media not in {"application/json", "application/blocks"}:
        raise PushRefusal(415, "UNSUPPORTED_MEDIA_TYPE", "The body must be application/json or application/blocks.")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError:
            raise PushRefusal(400, "INVALID_CONTENT_LENGTH", "Content-Length is not a number.") from None
        if declared < 0:
            raise PushRefusal(400, "INVALID_CONTENT_LENGTH", "Content-Length is negative.")
        if declared > MAX_BODY_BYTES:
            raise PushRefusal(
                413,
                "PAYLOAD_TOO_LARGE",
                "The body is larger than 16 MiB.",
                extra={"limitBytes": MAX_BODY_BYTES},
            )
    if len(body) > MAX_BODY_BYTES:
        raise PushRefusal(
            413,
            "PAYLOAD_TOO_LARGE",
            "The body is larger than 16 MiB.",
            extra={"limitBytes": MAX_BODY_BYTES},
        )


def parse_bound(value: object, *, end: bool) -> datetime:
    if not isinstance(value, str) or not value:
        raise PushRefusal(400, "INVALID_DATE", "A date bound is invalid.")
    if _DATE.fullmatch(value):
        year, month, day = (int(part) for part in value.split("-"))
        try:
            if end:
                return datetime(year, month, day, 23, 59, 59, 999000, tzinfo=timezone.utc)
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            raise PushRefusal(400, "INVALID_DATE", "A date bound is invalid.") from None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise PushRefusal(400, "INVALID_DATE", "A date bound is invalid.") from None
    if parsed.tzinfo is None:
        raise PushRefusal(400, "INVALID_DATE", "A date bound needs an offset.")
    return parsed.astimezone(timezone.utc)


def parse_retrieve(body: object) -> dict:
    if not isinstance(body, dict):
        raise PushRefusal(400, "INVALID_JSON", "The body is not a JSON object.")
    unknown = set(body) - _RETRIEVE_KEYS
    if unknown:
        raise PushRefusal(400, "INVALID_FILTER", "The retrieve body has an unknown field.")
    query = body.get("query")
    if not isinstance(query, str) or not query.strip():
        raise PushRefusal(400, "INVALID_QUERY", "query is empty.")
    if "rewriteQuery" in body:
        if body["rewriteQuery"] is True:
            raise PushRefusal(400, "REWRITE_DISABLED", "Query rewriting is disabled.")
        if body["rewriteQuery"] is not False:
            raise PushRefusal(400, "REWRITE_DISABLED", "rewriteQuery must be false.")
    limit = body.get("limit", 8)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise PushRefusal(422, "LIMIT_OUT_OF_RANGE", "limit must be from 1 to 50.")
    filters = body.get("filters", {})
    if filters is None:
        filters = {}
    if not isinstance(filters, dict):
        raise PushRefusal(400, "INVALID_FILTER", "filters must be an object.")
    if set(filters) - _FILTER_KEYS:
        raise PushRefusal(400, "INVALID_FILTER", "filters has an unknown key.")
    kb = filters.get("kb") or []
    if not isinstance(kb, list) or any(not isinstance(item, str) for item in kb):
        raise PushRefusal(400, "INVALID_FILTER", "filters.kb must be a list of ids.")
    kb_ids = [item for item in kb if item] or None
    max_per = body.get("maxChunksPerRecord")
    if max_per is not None and (isinstance(max_per, bool) or not isinstance(max_per, int) or not 1 <= max_per <= 50):
        raise PushRefusal(422, "LIMIT_OUT_OF_RANGE", "maxChunksPerRecord must be from 1 to 50.")
    renamed = {}
    for key, value in (
        ("createdAfter", "created_after"),
        ("createdBefore", "created_before"),
        ("modifiedAfter", "modified_after"),
        ("modifiedBefore", "modified_before"),
    ):
        if key in body and body[key] is not None:
            renamed[value] = parse_bound(body[key], end=key.endswith("Before"))
    return {
        "query": query.strip(),
        "limit": limit,
        "kb_ids": kb_ids,
        "max_per": max_per,
        "bounds": renamed,
    }


_REBUILD_LOCK = "vector-store-rebuild"


def _release_rebuild(app) -> None:
    try:
        app.state.redis.delete(_REBUILD_LOCK)
    except redis.RedisError:
        pass


def _rebuild_gate(app) -> None:
    if not rebuild_enabled():
        raise PushRefusal(403, "REBUILD_DISABLED", "Vector store rebuild is disabled. Set ENABLE_VECTOR_STORE_REBUILD=true.")
    _require_postgres(app)
    _require_redis(app)
    with app.state.db.connect() as conn:
        busy = conn.execute(
            "select 1 from records where indexing_status = 'IN_PROGRESS' limit 1"
        ).fetchone()
    if busy:
        raise PushRefusal(409, "SYNC_IN_PROGRESS", "A sync or ingest is running.")
    if not app.state.redis.set(_REBUILD_LOCK, "1", nx=True, ex=3600):
        raise PushRefusal(409, "REBUILD_RUNNING", "A vector-store cleanup or reindex is already running.")


def _publish_rows(app, rows) -> None:
    for row in rows:
        publish(
            app.state.redis,
            "reindexRecord",
            record_id=str(row["record_id"]),
            kb_id=row["kb_id"],
            external_record_id=row["external_record_id"],
            version=int(row["version"]),
            content_rev=row["content_rev"] or "",
            lanes=app.state.settings.redis_lanes,
        )


def _queue_records(app, kb_id: str) -> JSONResponse:
    _require_postgres(app)
    _require_redis(app)
    with app.state.db.connect() as conn:
        rows = conn.execute(
            """
            update records set indexing_status = 'QUEUED', failure_reason = null, updated_at = now()
            where kb_id = %s and coalesce(stored_path, '') <> ''
            returning record_id, kb_id, external_record_id, version, content_rev
            """,
            (kb_id,),
        ).fetchall()
        conn.commit()
    seen = set()
    unique = []
    for row in rows:
        if row["record_id"] in seen:
            continue
        seen.add(row["record_id"])
        unique.append(row)
    _publish_rows(app, unique)
    return JSONResponse(status_code=202, content={"queued": len(unique), "connectorId": kb_id})


def _vector_store_job(app, operation: str) -> JSONResponse:
    _rebuild_gate(app)
    try:
        if operation == "cleanup":
            try:
                app.state.vectors.drop()
                app.state.vectors.ensure(app.state.embedder.dim)
            except QdrantUnavailable:
                raise PushRefusal(503, "QDRANT_UNAVAILABLE", "Qdrant is unavailable.") from None
            with app.state.db.connect() as conn:
                conn.execute(
                    """
                    update records set indexing_status = 'NOT_STARTED', failure_reason = null, updated_at = now()
                    """
                )
                conn.commit()
            return JSONResponse(status_code=202, content={"accepted": True, "operation": "cleanup"})
        try:
            rows = app.state.engine.queue_reindex()
        except psycopg.Error:
            raise PushRefusal(503, "POSTGRES_UNAVAILABLE", "Postgres is unavailable.") from None
        seen = set()
        unique = []
        for row in rows:
            if row["record_id"] in seen:
                continue
            seen.add(row["record_id"])
            unique.append(row)
        _publish_rows(app, unique)
        return JSONResponse(status_code=202, content={"accepted": True, "operation": "reindex", "queued": len(unique)})
    finally:
        _release_rebuild(app)


async def _put_embedding(app, request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        raise PushRefusal(400, "ENVELOPE_INVALID", "The embedding body is invalid.") from None
    if not isinstance(body, dict):
        raise PushRefusal(400, "ENVELOPE_INVALID", "The embedding body is invalid.")
    model = body.get("model")
    if not isinstance(model, str) or not model.strip():
        raise PushRefusal(400, "ENVELOPE_INVALID", "model is required.")
    model = model.strip()
    if model == app.state.settings.model:
        return JSONResponse({"model": model, "restartRequired": False})
    try:
        count = app.state.vectors.count()
    except QdrantUnavailable:
        raise PushRefusal(503, "QDRANT_UNAVAILABLE", "Qdrant is unavailable.") from None
    if count >= 1:
        raise PushRefusal(400, "MODEL_CHANGE_REFUSED", "The collection still has points.")
    dimension = body.get("dimension")
    if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension < 1:
        raise PushRefusal(400, "ENVELOPE_INVALID", "dimension is required when the model changes.")
    try:
        app.state.vectors.drop()
        app.state.vectors.ensure(dimension)
    except QdrantUnavailable:
        raise PushRefusal(503, "QDRANT_UNAVAILABLE", "Could not recreate the collection.") from None
    app.state.requested_model = model
    return JSONResponse({"model": model, "dimension": dimension, "restartRequired": True})


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="kbindex")
    app.state.settings = settings
    app.state.db = Database(settings.database_url)

    @app.exception_handler(PushRefusal)
    def _refused(_request: Request, exc: PushRefusal) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=error_body(exc))

    @app.exception_handler(psycopg.Error)
    def _postgres_down(_request: Request, exc: psycopg.Error) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content=error_body(PushRefusal(503, "POSTGRES_UNAVAILABLE", "Postgres is unavailable.")),
        )

    @app.on_event("startup")
    def startup() -> None:
        os.makedirs(settings.data_dir, exist_ok=True)
        app.state.db.migrate()
        app.state.redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        app.state.vectors = Vectors(settings.qdrant_url)
        app.state.embedder = load_embedder(settings.backend, settings.model, settings.device)
        app.state.engine = Engine(settings, app.state.db, app.state.vectors, app.state.embedder)
        app.state.redis.ping()
        ensure_group(app.state.redis, settings.redis_lanes)
        app.state.engine.ensure_generation()
        _republish_recovered(app)

    @app.post("/api/v1/kb")
    async def create_kb(request: Request) -> JSONResponse:
        try:
            payload = KbIn.model_validate(await request.json())
        except (ValidationError, json.JSONDecodeError):
            raise PushRefusal(400, "ENVELOPE_INVALID", "The knowledge base body is invalid.") from None
        kb_id = payload.id or str(uuid.uuid4())
        if not EXTERNAL_RECORD_ID.fullmatch(kb_id):
            raise PushRefusal(400, "ENVELOPE_INVALID", "id is invalid.", "id")
        name = (payload.name or kb_id).strip()
        if not name or len(name) > 255:
            raise PushRefusal(400, "ENVELOPE_INVALID", "name is invalid.", "name")
        with app.state.db.connect() as conn:
            existing = kb_row(conn, kb_id)
            if existing:
                return JSONResponse(status_code=200, content={"id": existing["id"], "name": existing["name"]})
            conn.execute("insert into knowledge_bases (id, name) values (%s, %s)", (kb_id, name))
            conn.commit()
        return JSONResponse(status_code=201, content={"id": kb_id, "name": name})

    @app.get("/api/v1/kb/{kb_id}")
    def get_kb(kb_id: str) -> JSONResponse:
        with app.state.db.connect() as conn:
            row = kb_row(conn, kb_id)
        if row is None:
            raise PushRefusal(404, "KB_NOT_FOUND", "Knowledge base not found.")
        return JSONResponse({"id": row["id"], "name": row["name"]})

    @app.put("/api/v1/kb/{kb_id}/schema")
    async def put_schema(kb_id: str, request: Request) -> JSONResponse:
        _require_kb(app, kb_id)
        try:
            payload = SchemaIn.model_validate(await request.json())
        except (ValidationError, json.JSONDecodeError):
            raise PushRefusal(400, "ENVELOPE_INVALID", "The schema body is invalid.") from None
        allowed = {"string", "integer", "number", "boolean", "string_list"}
        names = [item.name for item in payload.properties]
        if len(names) != len(set(names)):
            raise PushRefusal(400, "ENVELOPE_INVALID", "property names must be unique.")
        for item in payload.properties:
            if item.type not in allowed:
                raise PushRefusal(400, "ENVELOPE_INVALID", "property type is invalid.", item.name)
        stored = [{"name": item.name, "type": item.type} for item in payload.properties]
        with app.state.db.connect() as conn:
            conn.execute(
                """
                insert into schemas (kb_id, schema_id, properties) values (%s, %s, %s::jsonb)
                on conflict (kb_id, schema_id) do update set properties = excluded.properties
                """,
                (kb_id, payload.schemaId, json.dumps(stored)),
            )
            conn.commit()
        return JSONResponse({"schemaId": payload.schemaId, "properties": stored})

    @app.get("/api/v1/kb/{kb_id}/schema")
    def get_schema(kb_id: str) -> JSONResponse:
        _require_kb(app, kb_id)
        with app.state.db.connect() as conn:
            row = schema_row(conn, kb_id, None)
        if row is None:
            raise PushRefusal(404, "SCHEMA_NOT_FOUND", "This knowledge base has no schema.")
        return JSONResponse({"schemaId": row["schema_id"], "properties": row["properties"]})

    @app.post("/api/v1/kb/{kb_id}/records")
    async def push_record(kb_id: str, request: Request) -> JSONResponse:
        body = await request.body()
        admit(request.headers.get("content-type"), request.headers.get("content-length"), body)
        envelope = parse_envelope(body)
        _require_kb(app, kb_id)
        if envelope.metadata is not None:
            with app.state.db.connect() as conn:
                if not schema_exists(conn, kb_id, envelope.metadata.schemaId):
                    raise PushRefusal(422, "SCHEMA_NOT_FOUND", "metadata.schemaId is not registered.", "metadata.schemaId")
        _require_postgres(app)
        return _commit_push(app, kb_id, body, envelope)

    @app.delete("/api/v1/kb/{kb_id}/records/{external_record_id}")
    def delete_record(kb_id: str, external_record_id: str) -> JSONResponse:
        _require_postgres(app)
        _require_redis(app)
        rid = record_id_for(kb_id, external_record_id)
        with app.state.db.connect() as conn:
            row = lock_record(conn, rid)
            if row is None or row["kb_id"] != kb_id:
                raise PushRefusal(404, "RECORD_NOT_FOUND", "Record not found.")
            snapshot = dict(row)
            old_raw, old_stored = _read_pair(snapshot)
            delete_chunks_for(conn, rid)
            rebuild_bm25(conn)
            conn.execute("delete from records where record_id = %s", (rid,))
            conn.commit()
        _remove_files(snapshot)
        try:
            app.state.vectors.delete_record(str(rid))
        except QdrantUnavailable:
            pass
        try:
            publish(
                app.state.redis,
                "deleteRecord",
                record_id=str(rid),
                kb_id=kb_id,
                external_record_id=external_record_id,
                version=int(snapshot["version"]),
                content_rev=snapshot["content_rev"] or "",
                lanes=app.state.settings.redis_lanes,
            )
        except redis.RedisError:
            _restore_record(app, snapshot)
            _restore_files(snapshot, old_raw, old_stored)
            raise PushRefusal(503, "REDIS_UNAVAILABLE", "Redis is unavailable.") from None
        return JSONResponse({"deleted": True, "recordId": str(rid), "externalRecordId": external_record_id})

    @app.get("/api/v1/kb/{kb_id}/records/{external_record_id}")
    def record_status(kb_id: str, external_record_id: str) -> JSONResponse:
        row = _record(app, kb_id, external_record_id)
        if row is None:
            raise PushRefusal(404, "RECORD_NOT_FOUND", "Record not found.")
        return JSONResponse(_status_body(row))

    @app.get("/api/v1/kb/{kb_id}/indexing/counts")
    def counts(kb_id: str) -> JSONResponse:
        _require_kb(app, kb_id)
        with app.state.db.connect() as conn:
            return JSONResponse(counts_for(conn, kb_id))

    @app.post("/api/v1/kb/{kb_id}/records/{external_record_id}/reprocess")
    def reprocess(kb_id: str, external_record_id: str) -> JSONResponse:
        _require_redis(app)
        row = _record(app, kb_id, external_record_id)
        if row is None:
            raise PushRefusal(404, "RECORD_NOT_FOUND", "Record not found.")
        transition = apply(row["indexing_status"], "reprocess")
        if transition.refused:
            raise PushRefusal(409, "IN_PROGRESS", "The record is already processing.")
        with app.state.db.connect() as conn:
            conn.execute(
                "update records set indexing_status = 'QUEUED', failure_reason = null, updated_at = now() where record_id = %s",
                (row["record_id"],),
            )
            conn.commit()
        try:
            publish(
                app.state.redis,
                "reindexRecord",
                record_id=str(row["record_id"]),
                kb_id=kb_id,
                external_record_id=external_record_id,
                version=int(row["version"]),
                content_rev=row["content_rev"] or "",
                lanes=app.state.settings.redis_lanes,
            )
        except redis.RedisError:
            with app.state.db.connect() as conn:
                conn.execute(
                    "update records set indexing_status = %s, failure_reason = %s where record_id = %s",
                    (row["indexing_status"], row["failure_reason"], row["record_id"]),
                )
                conn.commit()
            raise PushRefusal(503, "REDIS_UNAVAILABLE", "Redis is unavailable.") from None
        return JSONResponse(status_code=202, content={"recordId": str(row["record_id"]), "indexingStatus": "QUEUED"})

    @app.get("/api/v1/records/{record_id}")
    def get_record_by_id(record_id: str) -> JSONResponse:
        return _record_by_uuid(app, record_id)

    @app.get("/api/v1/knowledgeBase/record/{record_id}")
    def get_knowledge_base_record(record_id: str) -> JSONResponse:
        return _record_by_uuid(app, record_id)

    @app.get("/api/v1/connectors/{connector_id}/stats")
    def connector_stats(connector_id: str) -> JSONResponse:
        _require_kb(app, connector_id)
        with app.state.db.connect() as conn:
            counts = counts_for(conn, connector_id)
        return JSONResponse(
            {
                "success": True,
                "data": {
                    "connectorId": connector_id,
                    "origin": "COLLECTION",
                    "stats": {"total": sum(counts.values()), "indexingStatus": counts},
                },
            }
        )

    @app.post("/api/v1/records/{record_id}/reindex")
    async def reindex_record(record_id: str, request: Request) -> JSONResponse:
        await request.body()
        row = _load_record_uuid(app, record_id)
        return reprocess(row["kb_id"], row["external_record_id"])

    @app.post("/api/v1/knowledgeBase/reindex/record/{record_id}")
    async def reindex_knowledge_base_record(record_id: str, request: Request) -> JSONResponse:
        return await reindex_record(record_id, request)

    @app.put("/api/v1/engineer/embedding")
    async def put_embedding(request: Request) -> JSONResponse:
        return await _put_embedding(app, request)

    @app.post("/api/v1/connectors/vector-store/cleanup")
    def vector_store_cleanup() -> JSONResponse:
        return _vector_store_job(app, operation="cleanup")

    @app.post("/api/v1/connectors/vector-store/reindex")
    def vector_store_reindex() -> JSONResponse:
        return _vector_store_job(app, operation="reindex")

    @app.post("/api/v1/connectors/{connector_id}/reindex")
    def reindex_connector(connector_id: str) -> JSONResponse:
        return _queue_records(app, kb_id=connector_id)

    @app.post("/api/v1/knowledgeBase/reindex/record-group/{record_group_id}")
    def reindex_record_group(record_group_id: str) -> JSONResponse:
        return _queue_records(app, kb_id=record_group_id)

    @app.post("/api/v1/retrieve")
    async def retrieve(request: Request) -> JSONResponse:
        return await _retrieve(app, request, debug=False)

    @app.post("/api/v1/debug/retrieve")
    async def debug_retrieve(request: Request) -> JSONResponse:
        return await _retrieve(app, request, debug=True)

    @app.get("/api/v1/debug/kb/{kb_id}/records/{external_record_id}")
    def debug_record(kb_id: str, external_record_id: str) -> JSONResponse:
        row = _record(app, kb_id, external_record_id)
        if row is None:
            raise PushRefusal(404, "RECORD_NOT_FOUND", "Record not found.")
        raw = json.loads(Path(row["raw_path"]).read_bytes())
        normalized = Path(row["stored_path"]).read_text(encoding="utf-8")
        payload = json.loads(normalized)
        pieces = build_pieces(str(row["record_id"]), payload, app.state.embedder)
        counts: dict[int, int] = {}
        for piece in pieces:
            counts[piece.block_index] = counts.get(piece.block_index, 0) + 1
        return JSONResponse(
            {
                "raw": raw,
                "normalized": normalized,
                "blocks": [
                    {"index": index, "type": kind, "text": text}
                    for index, kind, text in texts_of_stored(payload)
                ],
                "chunks": [
                    {
                        "chunkId": chunk_public_id(str(row["record_id"]), piece.block_index, piece.piece, counts[piece.block_index]),
                        "text": piece.text,
                        "blockIndex": piece.block_index,
                        "piece": piece.piece,
                        "tokenCount": piece.token_count,
                    }
                    for piece in pieces
                ],
            }
        )

    return app


def _commit_push(app: FastAPI, kb_id: str, raw: bytes, envelope) -> JSONResponse:
    prepared = prepare(envelope)
    rid = record_id_for(kb_id, envelope.externalRecordId)
    has_text = has_indexable_text(envelope)
    directory = Path(app.state.settings.data_dir)
    conn = app.state.db.connect()
    previous = None
    wrote = False
    try:
        conn.execute("select pg_advisory_xact_lock(hashtextextended(%s, 0))", (str(rid),))
        previous = lock_record(conn, rid)
        if previous is not None and previous["kb_id"] != kb_id:
            previous = None
        decision = decide(
            stored_version=None if previous is None else int(previous["version"]),
            stored_blocks_sha=None if previous is None else previous["blocks_sha"],
            stored_request_digest=None if previous is None else _digest_of_revision(previous["revision_id"]),
            version=envelope.version,
            blocks_sha=prepared.blocks_sha,
            request_digest=prepared.request_digest,
        )
        if decision.action in {"stale", "conflict"}:
            conn.rollback()
            raise PushRefusal(
                409,
                decision.reason or "VERSION_CONFLICT",
                "Version refused.",
                extra={"currentVersion": decision.current_version},
            )
        if decision.action == "unchanged":
            conn.rollback()
            return JSONResponse(_success(previous, kb_id, "unchanged", False, None, envelope))
        old_raw, old_stored = _read_pair(previous)
        raw_path, stored_path = write_payload(directory, kb_id, str(rid), raw, prepared.stored)
        wrote = True
        if decision.action == "create":
            status = apply(None, "push", has_text=has_text).status
            event = "newRecord"
            publish_it = status == "QUEUED"
            conn.execute(
                """
                insert into records (
                  record_id, kb_id, external_record_id, version, revision_id, content_rev, blocks_sha,
                  record_name, source_modified_ms, indexing_status, failure_reason, raw_path, stored_path
                ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,null,%s,%s)
                """,
                (
                    rid, kb_id, envelope.externalRecordId, envelope.version, prepared.revision,
                    prepared.content_rev, prepared.blocks_sha, envelope.recordName,
                    envelope.sourceLastModifiedTimestamp, status, raw_path, stored_path,
                ),
            )
            _write_graph(conn, rid, prepared.stored)
            http = 201
            label = "created"
            changed = True
        elif decision.action == "metadata":
            status = previous["indexing_status"]
            event = None
            publish_it = False
            conn.execute(
                """
                update records set version = %s, revision_id = %s, content_rev = %s, blocks_sha = %s,
                  record_name = %s, source_modified_ms = %s, raw_path = %s, stored_path = %s, updated_at = now()
                where record_id = %s
                """,
                (
                    envelope.version, prepared.revision, prepared.content_rev, prepared.blocks_sha,
                    envelope.recordName, envelope.sourceLastModifiedTimestamp, raw_path, stored_path, rid,
                ),
            )
            http = 200
            label = "updated"
            changed = False
        else:
            status = apply(previous["indexing_status"], "push", has_text=has_text).status
            event = "updateRecord"
            publish_it = True
            delete_chunks_for(conn, rid)
            rebuild_bm25(conn)
            conn.execute(
                """
                update records set version = %s, revision_id = %s, content_rev = %s, blocks_sha = %s,
                  record_name = %s, source_modified_ms = %s, indexing_status = %s, failure_reason = null,
                  raw_path = %s, stored_path = %s, updated_at = now()
                where record_id = %s
                """,
                (
                    envelope.version, prepared.revision, prepared.content_rev, prepared.blocks_sha,
                    envelope.recordName, envelope.sourceLastModifiedTimestamp, status, raw_path, stored_path, rid,
                ),
            )
            _write_graph(conn, rid, prepared.stored)
            http = 200
            label = "updated"
            changed = True
        if publish_it:
            try:
                app.state.redis.ping()
            except redis.RedisError:
                conn.rollback()
                if wrote:
                    _restore_files(previous, old_raw, old_stored)
                    if previous is None:
                        _remove_new_files(app, kb_id, rid)
                raise PushRefusal(503, "REDIS_UNAVAILABLE", "Redis is unavailable.") from None
        conn.commit()
    except psycopg.Error:
        conn.rollback()
        if wrote:
            _restore_files(previous, old_raw, old_stored)
            if previous is None:
                _remove_new_files(app, kb_id, rid)
        raise PushRefusal(503, "POSTGRES_UNAVAILABLE", "Postgres is unavailable.") from None
    finally:
        conn.close()
    if decision.action == "content":
        try:
            app.state.vectors.delete_record(str(rid))
        except QdrantUnavailable:
            pass
    if publish_it and event:
        try:
            publish(
                app.state.redis,
                event,
                record_id=str(rid),
                kb_id=kb_id,
                external_record_id=envelope.externalRecordId,
                version=envelope.version,
                content_rev=prepared.content_rev,
                lanes=app.state.settings.redis_lanes,
            )
        except redis.RedisError:
            _compensate_push(app, previous, old_raw, old_stored, rid, kb_id)
            raise PushRefusal(503, "REDIS_UNAVAILABLE", "Redis is unavailable.") from None
    body = {
        "recordId": str(rid),
        "kbId": kb_id,
        "externalRecordId": envelope.externalRecordId,
        "version": envelope.version,
        "status": label,
        "contentChanged": changed,
        "contentRev": prepared.content_rev,
        "schemaId": envelope.metadata.schemaId if envelope.metadata else None,
        "event": event,
        "indexingStatus": status,
    }
    return JSONResponse(status_code=http, content=body)


def _write_graph(conn, rid, stored: bytes) -> None:
    payload = json.loads(stored)
    graph = [(index, parent_of(payload, index), kind, text) for index, kind, text in texts_of_stored(payload)]
    replace_graph(conn, rid, graph)
    replace_groups(conn, rid, groups_of(payload))


def _compensate_push(app, previous, old_raw, old_stored, rid, kb_id: str) -> None:
    with app.state.db.connect() as conn:
        if previous is None:
            delete_chunks_for(conn, rid)
            conn.execute("delete from records where record_id = %s", (rid,))
            conn.commit()
            _remove_new_files(app, kb_id, rid)
            return
        else:
            conn.execute(
                """
                update records set version = %s, revision_id = %s, content_rev = %s, blocks_sha = %s,
                  record_name = %s, source_modified_ms = %s, indexing_status = %s, failure_reason = %s,
                  raw_path = %s, stored_path = %s, updated_at = %s
                where record_id = %s
                """,
                (
                    previous["version"], previous["revision_id"], previous["content_rev"], previous["blocks_sha"],
                    previous["record_name"], previous["source_modified_ms"], previous["indexing_status"],
                    previous["failure_reason"], previous["raw_path"], previous["stored_path"], previous["updated_at"], rid,
                ),
            )
        conn.commit()
    _restore_files(previous, old_raw, old_stored)


def _restore_files(previous, old_raw: bytes | None, old_stored: bytes | None) -> None:
    if previous is None:
        return
    if old_raw is not None and previous["raw_path"]:
        Path(previous["raw_path"]).write_bytes(old_raw)
    if old_stored is not None and previous["stored_path"]:
        Path(previous["stored_path"]).write_bytes(old_stored)


def _read_pair(previous) -> tuple[bytes | None, bytes | None]:
    if previous is None:
        return None, None
    raw = Path(previous["raw_path"]).read_bytes() if previous["raw_path"] and Path(previous["raw_path"]).exists() else None
    stored = Path(previous["stored_path"]).read_bytes() if previous["stored_path"] and Path(previous["stored_path"]).exists() else None
    return raw, stored


def _remove_new_files(app, kb_id: str, rid) -> None:
    folder = Path(app.state.settings.data_dir) / kb_id
    for suffix in (".raw.json", ".stored.json"):
        path = folder / f"{rid}{suffix}"
        if path.exists():
            path.unlink()


def _remove_files(row) -> None:
    for key in ("raw_path", "stored_path"):
        path = row.get(key)
        if path and os.path.exists(path):
            os.remove(path)


def _restore_record(app, snapshot: dict) -> None:
    with app.state.db.connect() as conn:
        existing = record_row(conn, snapshot["record_id"])
        if existing is None:
            conn.execute(
                """
                insert into records (
                  record_id, kb_id, external_record_id, version, revision_id, content_rev, blocks_sha,
                  record_name, source_modified_ms, indexing_status, failure_reason, raw_path, stored_path,
                  created_at, updated_at
                ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    snapshot["record_id"], snapshot["kb_id"], snapshot["external_record_id"], snapshot["version"],
                    snapshot["revision_id"], snapshot["content_rev"], snapshot["blocks_sha"], snapshot["record_name"],
                    snapshot["source_modified_ms"], snapshot["indexing_status"], snapshot["failure_reason"],
                    snapshot["raw_path"], snapshot["stored_path"], snapshot["created_at"], snapshot["updated_at"],
                ),
            )
            conn.commit()


async def _retrieve(app, request: Request, *, debug: bool) -> JSONResponse:
    try:
        payload = json.loads(await request.body() or b"null")
    except json.JSONDecodeError:
        raise PushRefusal(400, "INVALID_JSON", "The body is not valid JSON.") from None
    parsed = parse_retrieve(payload)
    _require_postgres(app)
    if not app.state.vectors.ping():
        raise PushRefusal(503, "QDRANT_UNAVAILABLE", "Qdrant is unavailable.")
    try:
        found = app.state.engine.search(
            parsed["query"],
            limit=parsed["limit"],
            kb_ids=parsed["kb_ids"],
            max_per_record=parsed["max_per"],
            bounds=parsed["bounds"],
        )
    except QdrantUnavailable:
        raise PushRefusal(503, "QDRANT_UNAVAILABLE", "Qdrant is unavailable.") from None
    except psycopg.Error:
        raise PushRefusal(503, "POSTGRES_UNAVAILABLE", "Postgres is unavailable.") from None
    response = {"chunks": found["chunks"], "incomplete": False}
    if debug:
        response["breakdown"] = _breakdown(found)
    return JSONResponse(response)


def _breakdown(found: dict) -> list[dict]:
    rows = []
    for item in found["fused"][:50]:
        cid, score, _row = item
        entry = {
            "chunkId": cid,
            "dense": _leg(found["dense"], cid),
            "fastembed": _leg(found["keyword"].get("fastembed", []), cid),
            "rrf": score,
        }
        rows.append(entry)
    return rows


def _leg(pairs, chunk_id: str):
    for rank, (cid, score) in enumerate(pairs, start=1):
        if cid == chunk_id:
            return {"rank": rank, "score": score}
    return None


def _success(existing, kb_id: str, status: str, changed: bool, event, envelope) -> dict:
    return {
        "recordId": str(existing["record_id"]),
        "kbId": kb_id,
        "externalRecordId": existing["external_record_id"],
        "version": existing["version"],
        "status": status,
        "contentChanged": changed,
        "contentRev": existing["content_rev"],
        "schemaId": envelope.metadata.schemaId if envelope.metadata else None,
        "event": event,
        "indexingStatus": existing["indexing_status"],
    }


def _load_record_uuid(app, record_id: str):
    try:
        uuid.UUID(record_id)
    except ValueError:
        raise PushRefusal(404, "RECORD_NOT_FOUND", "Record not found.") from None
    with app.state.db.connect() as conn:
        row = record_row(conn, record_id)
    if row is None:
        raise PushRefusal(404, "RECORD_NOT_FOUND", "Record not found.")
    return row


def _record_by_uuid(app, record_id: str) -> JSONResponse:
    return JSONResponse(_pipeshub_record(_load_record_uuid(app, record_id)))


def _pipeshub_record(row) -> dict:
    """Record inspection body on the PipesHub record paths.

    The UI reads `record.indexingStatus` and `record.reason`. Stages this
    service does not run (extraction, entities) are omitted.
    """
    status = _status_body(row)
    record = {
        "id": status["recordId"],
        "recordName": row["record_name"],
        "externalRecordId": status["externalRecordId"],
        "indexingStatus": status["indexingStatus"],
        "reason": status["failureReason"],
        "version": status["version"],
        "contentRev": status["contentRev"],
        "updatedAt": status["updatedAt"],
    }
    if "embedDone" in status:
        record["embedDone"] = status["embedDone"]
        record["embedTotal"] = status["embedTotal"]
    return {"record": record, "knowledgeBase": {"id": row["kb_id"]}}


def _status_body(row) -> dict:
    reason = row["failure_reason"]
    if row["indexing_status"] in {"COMPLETED", "EMPTY"}:
        reason = None
    body = {
        "recordId": str(row["record_id"]),
        "externalRecordId": row["external_record_id"],
        "version": row["version"],
        "indexingStatus": row["indexing_status"],
        "failureReason": reason,
        "contentRev": row["content_rev"],
        "updatedAt": _iso_z(row["updated_at"]),
    }
    if row["indexing_status"] == "IN_PROGRESS":
        body["embedDone"] = int(row["embed_done"] or 0)
        body["embedTotal"] = int(row["embed_total"] or 0)
    return body


def _iso_z(value) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _digest_of_revision(revision: str | None) -> str | None:
    if not revision:
        return None
    parts = revision.split(":")
    if len(parts) != 3:
        return None
    return parts[1]


def _record(app, kb_id: str, external_record_id: str):
    rid = record_id_for(kb_id, external_record_id)
    with app.state.db.connect() as conn:
        row = record_row(conn, rid)
    if row is None or row["kb_id"] != kb_id:
        return None
    return row


def _require_kb(app, kb_id: str) -> None:
    with app.state.db.connect() as conn:
        if kb_row(conn, kb_id) is None:
            raise PushRefusal(404, "KB_NOT_FOUND", "Knowledge base not found.")


def _require_postgres(app) -> None:
    if not app.state.db.ping():
        raise PushRefusal(503, "POSTGRES_UNAVAILABLE", "Postgres is unavailable.")


def _require_redis(app) -> None:
    try:
        app.state.redis.ping()
    except redis.RedisError:
        raise PushRefusal(503, "REDIS_UNAVAILABLE", "Redis is unavailable.") from None


def _republish_recovered(app) -> None:
    with app.state.db.connect() as conn:
        rows = recover_in_progress(conn)
        conn.commit()
    for row in rows:
        publish(
            app.state.redis,
            "reindexRecord",
            record_id=str(row["record_id"]),
            kb_id=row["kb_id"],
            external_record_id=row["external_record_id"],
            version=int(row["version"]),
            content_rev=row["content_rev"] or "",
            lanes=app.state.settings.redis_lanes,
        )


def main() -> None:
    import uvicorn

    settings = load_settings()
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.api_port)
