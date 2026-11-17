"""blocksFormat 1 push DTO. Closed, strict, same refusal reasons as PipesHub."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError, field_validator, model_validator

MAX_BLOCKS = 100_000
MAX_GROUPS = 20_000
MAX_ISSUES = 50
EXTERNAL_RECORD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~:-]{0,255}$")
HTML_TAG = re.compile(r"<[^>]{0,1000}>")
FORMAT_SPECIFIER = re.compile(r"(?<!\w)%(?:\d+\$)?[#0\-+ ]*\d*(?:\.\d+)?[a-zA-Z]")
IMAGE_URI = re.compile(r"^(?:data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+|storage://[0-9a-fA-F]{24})$")


class PushRefusal(Exception):
    def __init__(self, status: int, reason: str, message: str, location: str | None = None, issues: list[dict] | None = None, extra: dict | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.reason = reason
        self.message = message
        self.location = location
        self.issues = issues or []
        self.extra = extra or {}


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Citation(_M):
    section_title: str | None = Field(None, max_length=1024)
    page_number: int | None = Field(None, ge=0)
    line_number: int | None = Field(None, ge=0)
    paragraph_number: int | None = Field(None, ge=0)
    sheet_name: str | None = Field(None, max_length=1024)
    row_number: int | None = Field(None, ge=0)
    column_number: int | None = Field(None, ge=0)
    slide_number: int | None = Field(None, ge=0)


class TextBlock(_M):
    index: int = Field(ge=0)
    parent_index: int | None = Field(None, ge=0)
    type: Literal["text"]
    sub_type: Literal["paragraph", "heading", "quote", "list_item", "code", "equation", "divider", "link"] | None = None
    name: str | None = Field(None, max_length=1024)
    format: Literal["txt", "markdown", "html", "code", "json", "base64"] | None = None
    data: str = Field(max_length=1 << 20)
    weburl: str | None = None
    citation_metadata: Citation | None = None


class ImageBlock(_M):
    index: int = Field(ge=0)
    parent_index: int | None = Field(None, ge=0)
    type: Literal["image"]
    name: str | None = Field(None, max_length=1024)
    format: Literal["txt", "markdown", "html", "code", "json", "base64"] | None = None
    data: dict[str, str]
    weburl: str | None = None

    @field_validator("data")
    @classmethod
    def _uri(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) - {"uri"}:
            raise ValueError("unknown image data key")
        uri = value.get("uri")
        if not isinstance(uri, str) or not IMAGE_URI.match(uri):
            raise ValueError("image uri must be a data URI or storage://")
        return value


class RowData(_M):
    model_config = ConfigDict(extra="forbid", strict=True)
    cells: list[str] | None = Field(None, min_length=1, max_length=512)
    row_natural_language_text: str | None = Field(None, min_length=1, max_length=1 << 20)
    row_number: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def _one(self) -> Self:
        if not self.cells and not self.row_natural_language_text:
            raise ValueError("a table row needs cells or row_natural_language_text")
        return self


class TableRowBlock(_M):
    index: int = Field(ge=0)
    parent_index: int | None = Field(None, ge=0)
    type: Literal["table_row"]
    format: Literal["txt", "markdown", "html", "code", "json", "base64"] | None = None
    data: RowData
    name: str | None = None


class Group(_M):
    index: int = Field(ge=0)
    parent_index: int | None = Field(None, ge=0)
    type: Literal["text_section", "list", "ordered_list", "table"]
    name: str | None = Field(None, max_length=1024)
    data: str | None = Field(None, max_length=1 << 20)


class Blocks(_M):
    block_groups: list[Group] | None = Field(None, max_length=MAX_GROUPS)
    blocks: list[TextBlock | ImageBlock | TableRowBlock] | None = Field(None, max_length=MAX_BLOCKS)

    @model_validator(mode="after")
    def _linear(self) -> Self:
        blocks = self.blocks or []
        groups = self.block_groups or []
        ng = len(groups)
        for pos, block in enumerate(blocks):
            if block.index != pos:
                raise ValueError(f"blocks[{pos}].index is {block.index}; it must equal its position")
            if block.parent_index is not None and block.parent_index >= ng:
                raise ValueError(f"blocks[{pos}].parent_index is out of range")
        for pos, group in enumerate(groups):
            if group.index != pos:
                raise ValueError(f"block_groups[{pos}].index is {group.index}; it must equal its position")
            if group.parent_index is not None and group.parent_index >= ng:
                raise ValueError("parent out of range")
        depth = [0] * ng
        for start in range(ng):
            seen: list[int] = []
            cur: int | None = start
            guard = 0
            while cur is not None and depth[cur] == 0 and guard < ng + 2:
                depth[cur] = -1
                seen.append(cur)
                cur = groups[cur].parent_index
                guard += 1
            if cur is not None and depth[cur] == -1:
                raise ValueError("parent cycle")
            base = 0 if cur is None else depth[cur]
            for node in reversed(seen):
                base += 1
                if base > 64:
                    raise ValueError("block_groups nest deeper than 64")
                depth[node] = base
        return self


class Meta(_M):
    schemaId: str = Field(min_length=1, max_length=300)
    values: dict[str, Any] = Field(default_factory=dict)


class Envelope(_M):
    recordName: str = Field(max_length=255)
    mimeType: Literal["application/blocks"]
    externalRecordId: str
    version: int = Field(ge=0, le=2**53 - 1)
    blocksFormat: Literal[1]
    sourceLastModifiedTimestamp: int | None = Field(None, gt=0)
    metadata: Meta | None = None
    blocks: Blocks

    @field_validator("blocksFormat", "version", mode="before")
    @classmethod
    def _not_bool(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("expected a number, not true or false")
        return value

    @field_validator("recordName")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("recordName is empty")
        if "<" in value and HTML_TAG.search(value):
            raise ValueError("recordName must not contain HTML")
        if FORMAT_SPECIFIER.search(value):
            raise ValueError("recordName must not contain format specifiers")
        return value

    @field_validator("externalRecordId")
    @classmethod
    def _ext(cls, value: str) -> str:
        if not EXTERNAL_RECORD_ID.fullmatch(value):
            raise ValueError("externalRecordId is invalid")
        return value


def blocks_digest(blocks: Blocks) -> str:
    raw = blocks.model_dump_json(exclude_none=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def content_rev(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def format_location(loc: tuple) -> str:
    tags = {"text", "image", "table_row", "table", "text_section", "list", "ordered_list"}
    out = ""
    prev_int = False
    for seg in loc:
        if isinstance(seg, int):
            out += f"[{seg}]"
            prev_int = True
            continue
        if prev_int and seg in tags:
            prev_int = False
            continue
        prev_int = False
        out += ("." if out else "") + str(seg)
    return out


def refusal_from(exc: ValidationError) -> PushRefusal:
    errors = exc.errors(include_url=False, include_context=False, include_input=False)[:MAX_ISSUES]
    issues = [{"location": format_location(item["loc"]), "type": item["type"], "message": item["msg"]} for item in errors]
    if any(item["type"] == "json_invalid" for item in errors):
        return PushRefusal(400, "INVALID_JSON", "The body is not valid JSON.", issues=issues[:1])
    roots = {item["loc"][0] if item["loc"] else "" for item in errors}
    if roots - {"blocks", "metadata"}:
        bad = next(item for item in errors if (item["loc"][0] if item["loc"] else "") not in ("blocks", "metadata"))
        return PushRefusal(400, "ENVELOPE_INVALID", "The request envelope is invalid.", format_location(bad["loc"]), issues)
    if "blocks" in roots:
        bad = next(item for item in errors if item["loc"] and item["loc"][0] == "blocks")
        return PushRefusal(422, "BLOCKS_INVALID", "The blocks are invalid.", format_location(bad["loc"]), issues)
    first = errors[0]
    return PushRefusal(422, "PROPERTY_INVALID", "A metadata value is invalid.", format_location(first["loc"]), issues)


def parse_envelope(body: bytes) -> Envelope:
    try:
        return Envelope.model_validate_json(body)
    except ValidationError as exc:
        raise refusal_from(exc) from None


_CODES = {
    400: "HTTP_BAD_REQUEST",
    404: "HTTP_NOT_FOUND",
    409: "HTTP_CONFLICT",
    413: "HTTP_PAYLOAD_TOO_LARGE",
    415: "HTTP_UNSUPPORTED_MEDIA_TYPE",
    422: "HTTP_UNPROCESSABLE_ENTITY",
    503: "HTTP_SERVICE_UNAVAILABLE",
}


def error_body(refusal: PushRefusal) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": _CODES.get(refusal.status, "HTTP_ERROR"),
        "reason": refusal.reason,
        "message": refusal.message,
    }
    if refusal.location:
        error["location"] = refusal.location
    if refusal.issues:
        error["issues"] = refusal.issues[:50]
    for key in ("currentVersion", "limitBytes"):
        if key in refusal.extra:
            error[key] = refusal.extra[key]
    return {"error": error}


def block_text(block: TextBlock | ImageBlock | TableRowBlock) -> str:
    if isinstance(block, TextBlock):
        return block.data
    if isinstance(block, TableRowBlock):
        if block.data.cells:
            return "\t".join(block.data.cells)
        return block.data.row_natural_language_text or ""
    return ""
