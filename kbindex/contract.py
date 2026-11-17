"""blocksFormat 1 push DTO. Closed, strict, same refusal shape as PipesHub."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    UrlConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

MAX_BLOCKS = 100_000
MAX_GROUPS = 20_000
MAX_RANGES_PER_GROUP = 1_000
MAX_GROUP_DEPTH = 64
MAX_CELLS = 512
MAX_VALUES = 256
MAX_ISSUES = 50
MAX_BODY_BYTES = 16 << 20
NORMALISER = "pb1"
EXTERNAL_RECORD_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._~:-]{0,255}$"
EXTERNAL_RECORD_ID = re.compile(EXTERNAL_RECORD_ID_PATTERN)
_HTML_TAG = re.compile(r"<[^>]{0,1000}>")
_FORMAT_SPECIFIER = re.compile(
    r"(?<!\w)%(?:\d{1,10}\$)?[#0\-+ ]{0,10}(?:\d{1,10})?(?:\.\d{1,10})?(?:h{1,2}|l{1,2}|L|z|j|t)?[nsxXp]"
)
_FAIL_FAST: dict[str, Any] = {"fail_fast": True}
_TAGS = {"text", "image", "table_row", "table", "text_section", "list", "ordered_list"}

WebUrl = Annotated[AnyUrl, UrlConstraints(max_length=2048, allowed_schemes=["http", "https"], host_required=True)]


class PushRefusal(Exception):
    def __init__(
        self,
        status: int,
        reason: str,
        message: str,
        location: str | None = None,
        issues: list[dict] | None = None,
        extra: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.reason = reason
        self.message = message
        self.location = location
        self.issues = issues or []
        self.extra = extra or {}


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    KEEP_EMPTY: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _empty_is_absent(self) -> Self:
        for name in type(self).model_fields:
            if name in self.KEEP_EMPTY:
                continue
            value = getattr(self, name)
            if value == [] or value == {} or (
                isinstance(value, BaseModel) and value.model_dump(exclude_none=True, exclude_defaults=True) == {}
            ):
                object.__setattr__(self, name, None)
        return self


class Range(_M):
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.start > self.end:
            raise ValueError("range start is after its end")
        return self


class Children(_M):
    block_ranges: list[Range] | None = Field(None, max_length=MAX_RANGES_PER_GROUP, **_FAIL_FAST)
    block_group_ranges: list[Range] | None = Field(None, max_length=MAX_RANGES_PER_GROUP, **_FAIL_FAST)


class ImageData(_M):
    uri: str = Field(min_length=1, max_length=28 << 20)


class RowData(_M):
    cells: list[str] | None = Field(None, min_length=1, max_length=MAX_CELLS, **_FAIL_FAST)
    row_natural_language_text: str | None = Field(None, min_length=1, max_length=1 << 20)
    row_number: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def _one(self) -> Self:
        if self.cells is None and self.row_natural_language_text is None:
            raise ValueError("a table row needs cells or row_natural_language_text")
        return self

    @field_validator("cells")
    @classmethod
    def _cell_length(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        for cell in value:
            if len(cell) > (1 << 20):
                raise ValueError("cell is longer than 1 MiB")
        return value


class TableData(_M):
    table_summary: str = Field(max_length=1 << 20)


class Citation(_M):
    section_title: str | None = Field(None, max_length=1024)
    page_number: int | None = Field(None, ge=0)
    line_number: int | None = Field(None, ge=0)
    paragraph_number: int | None = Field(None, ge=0)
    sheet_name: str | None = Field(None, max_length=1024)
    row_number: int | None = Field(None, ge=0)
    column_number: int | None = Field(None, ge=0)
    slide_number: int | None = Field(None, ge=0)


class ListMd(_M):
    list_style: Literal["bullet", "numbered", "checkbox", "dash"] | None = None
    indent_level: int = Field(0, ge=0, le=32)
    item_count: int | None = Field(None, ge=0)


class TableMd(_M):
    num_of_rows: int | None = Field(None, ge=0)
    num_of_cols: int | None = Field(None, ge=0)
    num_of_cells: int | None = Field(None, ge=0)
    has_header: bool = False
    column_names: list[str] | None = Field(None, max_length=MAX_CELLS, **_FAIL_FAST)
    captions: list[str] | None = Field(None, max_length=64, **_FAIL_FAST)
    footnotes: list[str] | None = Field(None, max_length=64, **_FAIL_FAST)


class RowMd(_M):
    row_number: int | None = Field(None, ge=0)
    row_span: int | None = Field(None, ge=1)
    is_header: bool = False


class _BlockBase(_M):
    index: int = Field(ge=0)
    parent_index: int | None = Field(None, ge=0)
    type: str
    sub_type: Literal["paragraph", "heading", "quote", "list_item", "code", "equation", "divider", "link"] | None = None
    name: str | None = Field(None, max_length=1024)
    format: Literal["txt", "markdown", "html", "code", "json", "base64"] | None = None
    data: Any = None
    weburl: WebUrl | None = None
    citation_metadata: Citation | None = None
    list_metadata: ListMd | None = None
    table_row_metadata: RowMd | None = None


class TextBlock(_BlockBase):
    type: Literal["text"]
    data: str = Field(max_length=1 << 20)


class ImageBlock(_BlockBase):
    type: Literal["image"]
    data: ImageData


class TableRowBlock(_BlockBase):
    type: Literal["table_row"]
    data: RowData


Block = Annotated[TextBlock | ImageBlock | TableRowBlock, Field(discriminator="type")]


class _GroupBase(_M):
    index: int = Field(ge=0)
    parent_index: int | None = Field(None, ge=0)
    type: str
    name: str | None = Field(None, max_length=1024)
    description: str | None = Field(None, max_length=1 << 20)
    requires_processing: bool = False
    format: Literal["txt", "markdown", "html"] | None = None
    data: Any = None
    children: Children | None = None
    weburl: WebUrl | None = None
    citation_metadata: Citation | None = None
    list_metadata: ListMd | None = None
    table_metadata: TableMd | None = None


class SectionGroup(_GroupBase):
    type: Literal["text_section", "list", "ordered_list"]
    data: str | None = Field(None, max_length=1 << 20)


class TableGroup(_GroupBase):
    type: Literal["table"]
    data: TableData | None = None


Group = Annotated[SectionGroup | TableGroup, Field(discriminator="type")]


def check_structure(blocks: list[Any], groups: list[Any]) -> None:
    """Indices match positions, a child is covered at most once, nesting stops at 64."""
    count_blocks, count_groups = len(blocks), len(groups)
    for pos, block in enumerate(blocks):
        if block.index != pos:
            raise ValueError(f"blocks[{pos}].index is {block.index}; it must equal its position")
        if block.parent_index is not None and block.parent_index >= count_groups:
            raise ValueError(f"blocks[{pos}].parent_index is out of range")
    for pos, group in enumerate(groups):
        if group.index != pos:
            raise ValueError(f"block_groups[{pos}].index is {group.index}; it must equal its position")
        if group.parent_index is not None and group.parent_index >= count_groups:
            raise ValueError(f"block_groups[{pos}].parent_index is out of range")
    covered_blocks = covered_groups = 0
    for gi, group in enumerate(groups):
        if group.children:
            covered_blocks += sum(item.end - item.start + 1 for item in group.children.block_ranges or [])
            covered_groups += sum(item.end - item.start + 1 for item in group.children.block_group_ranges or [])
            if covered_blocks > count_blocks or covered_groups > count_groups:
                raise ValueError(f"block_groups[{gi}].children cover more children than exist")
    block_owner = [-1] * count_blocks
    group_owner = [-1] * count_groups
    for gi, group in enumerate(groups):
        if not group.children:
            continue
        pairs = (
            (group.children.block_ranges, count_blocks, block_owner),
            (group.children.block_group_ranges, count_groups, group_owner),
        )
        for ranges, size, owner in pairs:
            for item in ranges or []:
                if item.end >= size:
                    raise ValueError(f"block_groups[{gi}].children range ends outside the list")
                for index in range(item.start, item.end + 1):
                    if owner[index] != -1:
                        raise ValueError(f"block_groups[{gi}].children lists a child that another range already lists")
                    owner[index] = gi
    depth = [0] * count_groups
    for start in range(count_groups):
        path: list[int] = []
        cur: int | None = start
        while cur is not None and depth[cur] == 0:
            depth[cur] = -1
            path.append(cur)
            cur = groups[cur].parent_index
        if cur is not None and depth[cur] == -1:
            raise ValueError(f"block_groups[{start}] has a parent cycle")
        base = 0 if cur is None else depth[cur]
        for node in reversed(path):
            base += 1
            if base > MAX_GROUP_DEPTH:
                raise ValueError(f"block_groups nest deeper than {MAX_GROUP_DEPTH}")
            depth[node] = base


class Blocks(_M):
    KEEP_EMPTY: ClassVar[frozenset[str]] = frozenset({"blocks"})
    block_groups: list[Group] | None = Field(None, max_length=MAX_GROUPS, **_FAIL_FAST)
    blocks: list[Block] | None = Field(None, max_length=MAX_BLOCKS, **_FAIL_FAST)

    @model_validator(mode="after")
    def _linear(self) -> Self:
        check_structure(self.blocks or [], self.block_groups or [])
        return self


def _check_meta_value(value: Any) -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("metadata values must be finite")
        return
    if isinstance(value, str):
        if len(value) > 1024:
            raise ValueError("metadata string is longer than 1024")
        return
    if isinstance(value, list):
        if len(value) > 64:
            raise ValueError("metadata list is longer than 64")
        for item in value:
            if not isinstance(item, str) or len(item) > 1024:
                raise ValueError("metadata list values must be short strings")
        return
    raise ValueError("metadata value type is not allowed")


class Meta(_M):
    KEEP_EMPTY: ClassVar[frozenset[str]] = frozenset({"values"})
    schemaId: str = Field(min_length=1, max_length=300)
    values: dict[str, Any] = Field(default_factory=dict)

    @field_validator("values")
    @classmethod
    def _values(cls, values: dict[str, Any]) -> dict[str, Any]:
        if len(values) > MAX_VALUES:
            raise ValueError("metadata has more than 256 values")
        for key, value in values.items():
            if not isinstance(key, str) or not key or len(key) > 64:
                raise ValueError("metadata key is empty or longer than 64")
            _check_meta_value(value)
        return values


class Envelope(_M):
    KEEP_EMPTY: ClassVar[frozenset[str]] = frozenset({"blocks"})
    recordName: str = Field(max_length=255)
    mimeType: Literal["application/blocks"]
    externalRecordId: str
    version: int = Field(ge=0, le=2**53 - 1)
    blocksFormat: Literal[1]
    sourceLastModifiedTimestamp: int | None = Field(None, gt=0)
    metadata: Meta | None = None
    blocks: Blocks

    @field_validator("blocksFormat", "version", "sourceLastModifiedTimestamp", mode="before")
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
        if "<" in value and _HTML_TAG.search(value):
            raise ValueError("recordName must not contain HTML")
        if _FORMAT_SPECIFIER.search(value):
            raise ValueError("recordName must not contain format specifiers")
        return value

    @field_validator("externalRecordId")
    @classmethod
    def _ext(cls, value: str) -> str:
        if not EXTERNAL_RECORD_ID.fullmatch(value):
            raise ValueError("externalRecordId has characters outside A-Z a-z 0-9 . _ ~ : - or is too long")
        return value


class Stored(_M):
    block_groups: list[Group] | None = None
    blocks: list[Block] | None = None
    properties: dict | None = None
    push_format: int


def canonical_blocks(blocks: Blocks) -> bytes:
    return blocks.model_dump_json(exclude_none=True, exclude_defaults=True).encode()


def blocks_digest(blocks: Blocks) -> str:
    return hashlib.sha256(canonical_blocks(blocks)).hexdigest()


def canonical_properties(schema_id: str, values: dict[str, Any]) -> dict[str, Any]:
    kept = {key: values[key] for key in sorted(values) if values[key] is not None}
    return {"schemaId": schema_id, "values": kept}


def canonical_properties_bytes(properties: dict[str, Any] | None) -> bytes:
    if properties is None:
        return b"{}"
    return json.dumps(properties, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def stored_bytes(blocks: Blocks, properties: dict[str, Any] | None) -> bytes:
    stored = Stored.model_construct(
        block_groups=blocks.block_groups,
        blocks=blocks.blocks,
        properties=properties,
        push_format=1,
    )
    return stored.model_dump_json(exclude_none=True, exclude_defaults=True).encode()


def request_digest(blocks_sha: str, properties: dict[str, Any] | None) -> str:
    """Same bytes as PipesHub request_digest with no image fingerprint."""
    digest = hashlib.sha256(NORMALISER.encode() + b"\x1f")
    digest.update(bytes.fromhex(blocks_sha))
    digest.update(canonical_properties_bytes(properties))
    return digest.hexdigest()


def content_rev(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def revision_id(digest: str, rev: str) -> str:
    return f"{NORMALISER}:{digest}:{rev}"


def properties_of(envelope: Envelope) -> dict[str, Any] | None:
    if envelope.metadata is None:
        return None
    return canonical_properties(envelope.metadata.schemaId, dict(envelope.metadata.values))


def format_location(loc: tuple) -> str:
    out = ""
    prev_int = False
    for seg in loc:
        if isinstance(seg, int):
            out += f"[{seg}]"
            prev_int = True
            continue
        if prev_int and seg in _TAGS:
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
    loc = first["loc"]
    name = str(loc[2]) if len(loc) > 2 and loc[1] == "values" else None
    return PushRefusal(422, "PROPERTY_INVALID", "A metadata value is invalid.", name or format_location(loc), issues)


def _has_surrogate(value: Any) -> bool:
    if isinstance(value, str):
        return any(0xD800 <= ord(char) <= 0xDFFF for char in value)
    if isinstance(value, dict):
        return any(_has_surrogate(key) or _has_surrogate(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_has_surrogate(item) for item in value)
    return False


def parse_envelope(body: bytes) -> Envelope:
    if not body or not body.strip():
        raise PushRefusal(400, "INVALID_JSON", "The body is not valid JSON.")
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, RecursionError, ValueError):
        raise PushRefusal(400, "INVALID_JSON", "The body is not valid JSON.") from None
    if not isinstance(parsed, dict):
        raise PushRefusal(400, "INVALID_JSON", "The body is not valid JSON.")
    if _has_surrogate(parsed):
        raise PushRefusal(400, "INVALID_JSON", "The body is not valid JSON.")
    try:
        return Envelope.model_validate(parsed)
    except ValidationError as exc:
        raise refusal_from(exc) from None
    except RecursionError:
        raise PushRefusal(400, "INVALID_JSON", "The body is not valid JSON.") from None


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
        error["issues"] = refusal.issues[:MAX_ISSUES]
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


def indexable_text(block: TextBlock | ImageBlock | TableRowBlock) -> str:
    return block_text(block).strip()
