"""HTTP API. Validation happens before any database call."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime

import redis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from kbindex.contract import PushRefusal, error_body, parse_envelope
from kbindex.db import Database, record_id_for
from kbindex.decide import decide
from kbindex.embed import load_embedder
from kbindex.pipeline import Engine, digest_of, rev_of, stored_from, write_payload
from kbindex.qdrant_store import Vectors
from kbindex.settings import Settings, load_settings

MAX_BODY = 16 << 20
STREAM = "record-events"
GROUP = "indexing"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="kbindex")
    app.state.settings = settings
    app.state.db = Database(settings.database_url)
    app.state.ready = False

    @app.on_event("startup")
    def startup() -> None:
        os.makedirs(settings.data_dir, exist_ok=True)
        app.state.db.migrate()
        app.state.redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        app.state.vectors = Vectors(settings.qdrant_url)
        app.state.embedder = load_embedder(settings.backend, settings.model, settings.device)
        app.state.engine = Engine(settings, app.state.db, app.state.vectors, app.state.embedder)
        try:
            app.state.redis.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        app.state.ready = True

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.post("/api/v1/kb")
    async def create_kb(request: Request) -> JSONResponse:
        body = await request.json()
        kb_id = body.get("id") or str(uuid.uuid4())
        name = body.get("name") or kb_id
        with app.state.db.connect() as conn:
            existing = conn.execute("select id, name from knowledge_bases where id = %s", (kb_id,)).fetchone()
            if existing:
                return JSONResponse(status_code=200, content={"id": existing["id"], "name": existing["name"]})
            conn.execute("insert into knowledge_bases (id, name) values (%s, %s)", (kb_id, name))
            conn.commit()
        return JSONResponse(status_code=201, content={"id": kb_id, "name": name})

    @app.get("/api/v1/kb/{kb_id}")
    def get_kb(kb_id: str) -> JSONResponse:
        with app.state.db.connect() as conn:
            row = conn.execute("select id, name from knowledge_bases where id = %s", (kb_id,)).fetchone()
        if row is None:
            return _err(404, "KB_NOT_FOUND", "Knowledge base not found.")
        return JSONResponse({"id": row["id"], "name": row["name"]})

    @app.put("/api/v1/kb/{kb_id}/schema")
    async def put_schema(kb_id: str, request: Request) -> JSONResponse:
        if not _kb_exists(app, kb_id):
            return _err(404, "KB_NOT_FOUND", "Knowledge base not found.")
        body = await request.json()
        schema_id = body.get("schemaId")
        props = body.get("properties") or []
        if not isinstance(schema_id, str) or not schema_id:
            return _err(400, "ENVELOPE_INVALID", "schemaId is required.", "schemaId")
        allowed = {"string", "integer", "number", "boolean", "string_list"}
        for prop in props:
            if set(prop) - {"name", "type"}:
                return _err(400, "ENVELOPE_INVALID", "unknown schema key")
            if prop.get("type") not in allowed:
                return _err(422, "PROPERTY_DEFINITION_INVALID", "unknown property type", prop.get("name"))
        with app.state.db.connect() as conn:
            conn.execute(
                """
                insert into schemas (kb_id, schema_id, properties) values (%s, %s, %s::jsonb)
                on conflict (kb_id, schema_id) do update set properties = excluded.properties
                """,
                (kb_id, schema_id, json.dumps(props)),
            )
            conn.commit()
        return JSONResponse({"schemaId": schema_id, "properties": props})

    @app.get("/api/v1/kb/{kb_id}/schema")
    def get_schema(kb_id: str, schemaId: str | None = None) -> JSONResponse:
        with app.state.db.connect() as conn:
            if schemaId:
                row = conn.execute(
                    "select schema_id, properties from schemas where kb_id = %s and schema_id = %s",
                    (kb_id, schemaId),
                ).fetchone()
            else:
                row = conn.execute(
                    "select schema_id, properties from schemas where kb_id = %s order by schema_id limit 1",
                    (kb_id,),
                ).fetchone()
        if row is None:
            return _err(404, "SCHEMA_NOT_FOUND", "No such schema.")
        return JSONResponse({"schemaId": row["schema_id"], "properties": row["properties"]})

    @app.post("/api/v1/kb/{kb_id}/records")
    async def push_record(kb_id: str, request: Request) -> JSONResponse:
        content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        if content_type not in {"application/json", "application/blocks"}:
            return _err(415, "UNSUPPORTED_MEDIA_TYPE", "The body must be application/json.")
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                length = int(declared)
            except ValueError:
                return _err(400, "INVALID_CONTENT_LENGTH", "Content-Length is not a number.")
            if length > MAX_BODY:
                return _err(413, "PAYLOAD_TOO_LARGE", "The body is larger than 16 MiB.", extra={"limitBytes": MAX_BODY})
        raw = await request.body()
        if len(raw) > MAX_BODY:
            return _err(413, "PAYLOAD_TOO_LARGE", "The body is larger than 16 MiB.", extra={"limitBytes": MAX_BODY})
        try:
            envelope = parse_envelope(raw)
        except PushRefusal as refusal:
            return JSONResponse(status_code=refusal.status, content=error_body(refusal))
        if not _kb_exists(app, kb_id):
            return _err(404, "KB_NOT_FOUND", "Knowledge base not found.")
        if envelope.metadata is not None:
            missing = _schema_missing(app, kb_id, envelope.metadata.schemaId)
            if missing:
                return _err(422, "SCHEMA_NOT_FOUND", "No such schema version.", "metadata.schemaId")
        if not app.state.db.ping():
            return _err(503, "POSTGRES_UNAVAILABLE", "Postgres is unavailable.")
        try:
            app.state.redis.ping()
        except Exception:
            return _err(503, "REDIS_UNAVAILABLE", "Redis is unavailable.")
        return _commit_push(app, kb_id, raw, envelope)

    @app.delete("/api/v1/kb/{kb_id}/records/{external_record_id}")
    def delete_record(kb_id: str, external_record_id: str) -> JSONResponse:
        rid = record_id_for(kb_id, external_record_id)
        with app.state.db.connect() as conn:
            row = conn.execute("select record_id, raw_path, stored_path from records where record_id = %s", (rid,)).fetchone()
            if row is None:
                return _err(404, "RECORD_NOT_FOUND", "Record not found.")
            conn.execute("delete from bm25_postings where chunk_id like %s", (str(rid) + ":%",))
            conn.execute("delete from records where record_id = %s", (rid,))
            conn.commit()
        for path in (row["raw_path"], row["stored_path"]):
            if path and os.path.exists(path):
                os.remove(path)
        try:
            app.state.vectors.delete_record(str(rid))
        except Exception:
            pass
        _publish(app, "deleteRecord", kb_id, external_record_id, rid, 0, "")
        return JSONResponse({"deleted": True, "recordId": str(rid), "externalRecordId": external_record_id})

    @app.get("/api/v1/kb/{kb_id}/records/{external_record_id}")
    def record_status(kb_id: str, external_record_id: str) -> JSONResponse:
        row = _record(app, kb_id, external_record_id)
        if row is None:
            return _err(404, "RECORD_NOT_FOUND", "Record not found.")
        body = _status_body(row)
        return JSONResponse(body)

    @app.get("/api/v1/kb/{kb_id}/indexing/counts")
    def counts(kb_id: str) -> JSONResponse:
        if not _kb_exists(app, kb_id):
            return _err(404, "KB_NOT_FOUND", "Knowledge base not found.")
        names = ["QUEUED", "IN_PROGRESS", "COMPLETED", "FAILED", "EMPTY"]
        out = {name: 0 for name in names}
        with app.state.db.connect() as conn:
            rows = conn.execute(
                "select indexing_status, count(*) as n from records where kb_id = %s group by indexing_status",
                (kb_id,),
            ).fetchall()
        for row in rows:
            if row["indexing_status"] in out:
                out[row["indexing_status"]] = row["n"]
        return JSONResponse(out)

    @app.post("/api/v1/kb/{kb_id}/records/{external_record_id}/reprocess")
    def reprocess(kb_id: str, external_record_id: str) -> JSONResponse:
        return _reprocess(app, kb_id, external_record_id)

    @app.post("/api/v1/records/{record_id}/reindex")
    def reindex(record_id: str) -> JSONResponse:
        with app.state.db.connect() as conn:
            row = conn.execute("select kb_id, external_record_id from records where record_id = %s", (record_id,)).fetchone()
        if row is None:
            return _err(404, "RECORD_NOT_FOUND", "Record not found.")
        return _reprocess(app, row["kb_id"], row["external_record_id"])

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
            return _err(404, "RECORD_NOT_FOUND", "Record not found.")
        raw = json.loads(open(row["raw_path"], encoding="utf-8").read()) if row["raw_path"] else None
        with app.state.db.connect() as conn:
            chunks = conn.execute(
                "select chunk_id, text, block_index, piece, token_count from chunks where record_id = %s order by block_index, piece",
                (row["record_id"],),
            ).fetchall()
        return JSONResponse({
            "received": raw,
            "chunks": [dict(item) for item in chunks],
        })

    @app.post("/api/v1/index/cleanup")
    def cleanup() -> JSONResponse:
        app.state.vectors.drop()
        with app.state.db.connect() as conn:
            conn.execute("delete from bm25_postings")
            conn.execute("delete from bm25_terms")
            conn.execute("delete from bm25_stats")
            conn.execute("delete from chunks")
            conn.execute("update records set indexing_status = 'QUEUED', failure_reason = null")
            conn.execute("delete from index_generation")
            conn.commit()
        return JSONResponse({"deleted": True})

    @app.post("/api/v1/index/reindex")
    def reindex_all() -> JSONResponse:
        if app.state.engine.model_change_blocked():
            return _model_refused()
        app.state.engine.ensure_generation()
        with app.state.db.connect() as conn:
            rows = conn.execute("select kb_id, external_record_id, version, content_rev, record_id from records").fetchall()
            conn.execute("update records set indexing_status = 'QUEUED', failure_reason = null")
            conn.commit()
        for row in rows:
            _publish(app, "reindexRecord", row["kb_id"], row["external_record_id"], row["record_id"], row["version"], row["content_rev"] or "")
        return JSONResponse(status_code=202, content={"fingerprint": app.state.settings.fingerprint, "queued": len(rows)})

    return app


def _commit_push(app: FastAPI, kb_id: str, raw: bytes, envelope) -> JSONResponse:
    settings: Settings = app.state.settings
    rid = record_id_for(kb_id, envelope.externalRecordId)
    digest = digest_of(envelope)
    stored = stored_from(envelope)
    rev = rev_of(stored)
    with app.state.db.connect() as conn:
        existing = conn.execute("select * from records where record_id = %s", (rid,)).fetchone()
        decision = decide(
            stored_version=None if existing is None else existing["version"],
            stored_digest=None if existing is None else existing["blocks_sha"],
            version=envelope.version,
            digest=digest,
        )
        if decision.action in {"stale", "conflict"}:
            return _err(409, decision.reason or "VERSION_CONFLICT", "Version refused.", extra={"currentVersion": decision.current_version})
        if decision.action == "unchanged":
            return JSONResponse(_success(existing, kb_id, "unchanged", False, None))
        raw_path, stored_path = write_payload(
            __import__("pathlib").Path(settings.data_dir), kb_id, str(rid), raw, stored
        )
        status = "QUEUED" if _has_text(envelope) else "EMPTY"
        event = None
        if decision.action == "create":
            conn.execute(
                """
                insert into records (
                  record_id, kb_id, external_record_id, version, revision_id, content_rev, blocks_sha,
                  record_name, source_modified_ms, indexing_status, raw_path, stored_path
                ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (rid, kb_id, envelope.externalRecordId, envelope.version, f"pb1:{digest}:{rev}", rev, digest,
                 envelope.recordName, envelope.sourceLastModifiedTimestamp, status, raw_path, stored_path),
            )
            event = "newRecord"
            http = 201
            changed = True
            label = "created"
        elif decision.action == "metadata":
            conn.execute(
                """
                update records set version = %s, record_name = %s, source_modified_ms = %s, updated_at = now()
                where record_id = %s
                """,
                (envelope.version, envelope.recordName, envelope.sourceLastModifiedTimestamp, rid),
            )
            http = 200
            changed = False
            label = "updated"
            status = existing["indexing_status"]
        else:
            conn.execute(
                """
                update records set version = %s, revision_id = %s, content_rev = %s, blocks_sha = %s,
                  record_name = %s, source_modified_ms = %s, indexing_status = %s, failure_reason = null,
                  raw_path = %s, stored_path = %s, updated_at = now()
                where record_id = %s
                """,
                (envelope.version, f"pb1:{digest}:{rev}", rev, digest, envelope.recordName,
                 envelope.sourceLastModifiedTimestamp, status, raw_path, stored_path, rid),
            )
            event = "updateRecord"
            http = 200
            changed = True
            label = "updated"
        conn.commit()
    if event and status == "QUEUED":
        _publish(app, event, kb_id, envelope.externalRecordId, rid, envelope.version, rev)
    row = _record(app, kb_id, envelope.externalRecordId)
    body = {
        "recordId": str(rid),
        "kbId": kb_id,
        "externalRecordId": envelope.externalRecordId,
        "version": envelope.version,
        "status": label,
        "contentChanged": changed,
        "contentRev": rev,
        "schemaId": envelope.metadata.schemaId if envelope.metadata else None,
        "event": event,
        "indexingStatus": row["indexing_status"] if row else status,
    }
    return JSONResponse(status_code=http, content=body)


def _success(existing, kb_id: str, status: str, changed: bool, event) -> dict:
    return {
        "recordId": str(existing["record_id"]),
        "kbId": kb_id,
        "externalRecordId": existing["external_record_id"],
        "version": existing["version"],
        "status": status,
        "contentChanged": changed,
        "contentRev": existing["content_rev"],
        "schemaId": None,
        "event": event,
        "indexingStatus": existing["indexing_status"],
    }


def _has_text(envelope) -> bool:
    for block in envelope.blocks.blocks or []:
        kind = getattr(block, "type", None)
        if kind == "text" and str(block.data).strip():
            return True
        if kind == "table_row":
            return True
    return False


def _publish(app, event_type: str, kb_id: str, external_record_id: str, record_id, version: int, content_rev: str) -> None:
    payload = {
        "recordId": str(record_id),
        "kbId": kb_id,
        "externalRecordId": external_record_id,
        "version": version,
        "contentRev": content_rev,
    }
    app.state.redis.xadd(STREAM, {"eventType": event_type, "payload": json.dumps(payload), "timestamp": datetime.utcnow().isoformat() + "Z"})


def _reprocess(app, kb_id: str, external_record_id: str) -> JSONResponse:
    row = _record(app, kb_id, external_record_id)
    if row is None:
        return _err(404, "RECORD_NOT_FOUND", "Record not found.")
    if row["indexing_status"] == "IN_PROGRESS":
        return _err(409, "IN_PROGRESS", "The record is already processing.")
    with app.state.db.connect() as conn:
        conn.execute(
            "update records set indexing_status = 'QUEUED', failure_reason = null, updated_at = now() where record_id = %s",
            (row["record_id"],),
        )
        conn.commit()
    _publish(app, "reindexRecord", kb_id, external_record_id, row["record_id"], row["version"], row["content_rev"] or "")
    return JSONResponse(status_code=202, content={"recordId": str(row["record_id"]), "indexingStatus": "QUEUED"})


def _status_body(row) -> dict:
    body = {
        "recordId": str(row["record_id"]),
        "externalRecordId": row["external_record_id"],
        "version": row["version"],
        "indexingStatus": row["indexing_status"],
        "failureReason": row["failure_reason"],
        "contentRev": row["content_rev"],
        "updatedAt": row["updated_at"].isoformat() if row["updated_at"] else None,
    }
    if row["indexing_status"] == "IN_PROGRESS":
        body["embedDone"] = row["embed_done"]
        body["embedTotal"] = row["embed_total"]
    return body


async def _retrieve(app, request: Request, *, debug: bool) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return _err(400, "INVALID_JSON", "The body is not valid JSON.")
    query = body.get("query")
    if not isinstance(query, str) or not query.strip():
        return _err(400, "ENVELOPE_INVALID", "query is empty.")
    limit = body.get("limit", 10)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 10:
        return JSONResponse(status_code=422, content=error_body(PushRefusal(422, "ENVELOPE_INVALID", "limit is out of range")))
    if body.get("rewriteQuery") is True:
        return _err(400, "REWRITE_DISABLED", "Query rewriting is disabled.")
    filters = body.get("filters") or {}
    if not isinstance(filters, dict):
        return _err(400, "ENVELOPE_INVALID", "filters must be an object.")
    allowed = {"apps", "kb", "recordGroups", "records", "recordsExact", "entityFilters"}
    permission = {"allowedApps", "allowedRecordGroups", "allowedRecords", "projectApps", "projectRecordGroups", "projectRecords", "connectionApps", "connectionRecordGroups", "connectionRecords", "selectionApps"}
    unknown = set(filters) - allowed - permission
    if unknown:
        return _err(400, "ENVELOPE_INVALID", "unknown filter")
    kb_ids = filters.get("kb") or []
    if kb_ids and not isinstance(kb_ids, list):
        return _err(400, "ENVELOPE_INVALID", "filters.kb must be a list")
    kb_id = kb_ids[0] if kb_ids else None
    if not app.state.vectors.ping():
        return _err(503, "QDRANT_UNAVAILABLE", "Qdrant is unavailable.")
    if not app.state.db.ping():
        return _err(503, "POSTGRES_UNAVAILABLE", "Postgres is unavailable.")
    if app.state.engine.model_change_blocked():
        return _model_refused()
    max_per = body.get("maxChunksPerRecord")
    found = app.state.engine.search(query.strip(), limit=limit, kb_id=kb_id, max_per_record=max_per)
    payload = {"chunks": found["chunks"], "incomplete": False}
    if debug:
        fused = {cid: score for cid, score in found["fused"]}
        payload["breakdown"] = []
        for cid, score in found["fused"][:50]:
            payload["breakdown"].append({
                "chunkId": cid,
                "dense": _leg(found["dense"], cid),
                "keyword": {name: _leg(pairs, cid) for name, pairs in found["keyword"].items()},
                "rrf": score,
            })
        del fused
    return JSONResponse(payload)


def _leg(pairs, chunk_id: str):
    for rank, (cid, score) in enumerate(pairs, start=1):
        if cid == chunk_id:
            return {"rank": rank, "score": score}
    return None


def _model_refused() -> JSONResponse:
    return JSONResponse(status_code=400, content={
        "status": "not healthy",
        "error": "Embedding model cannot be changed while the vector store contains data indexed with a different model. Please remove existing indexed documents first, then change the embedding model.",
    })


def _record(app, kb_id: str, external_record_id: str):
    rid = record_id_for(kb_id, external_record_id)
    with app.state.db.connect() as conn:
        return conn.execute("select * from records where record_id = %s and kb_id = %s", (rid, kb_id)).fetchone()


def _kb_exists(app, kb_id: str) -> bool:
    with app.state.db.connect() as conn:
        return conn.execute("select 1 from knowledge_bases where id = %s", (kb_id,)).fetchone() is not None


def _schema_missing(app, kb_id: str, schema_id: str) -> bool:
    with app.state.db.connect() as conn:
        return conn.execute(
            "select 1 from schemas where kb_id = %s and schema_id = %s",
            (kb_id, schema_id),
        ).fetchone() is None


def _err(status: int, reason: str, message: str, location: str | None = None, extra: dict | None = None) -> JSONResponse:
    refusal = PushRefusal(status, reason, message, location, extra=extra)
    return JSONResponse(status_code=status, content=error_body(refusal))


def main() -> None:
    import uvicorn

    settings = load_settings()
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.api_port)
