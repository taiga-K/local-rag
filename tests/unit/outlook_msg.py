"""A small Outlook .msg with a subject, a plain body, and one attachment name.

Attachment bytes are present so a test can show they are not indexed. oxmsg reads this file.
"""

from __future__ import annotations

import struct

_FREE = 0xFFFFFFFF
_END = 0xFFFFFFFE
_FAT = 0xFFFFFFFD
_SECRET = b"SECRET-9F3C"


def sample_msg(
    *,
    subject: str = "会議室の予約",
    body: str = "本文は第四会議室の鍵箱に入っています",
    filename: str = "見積書.txt",
    html: str = "",
    rtf: bytes = b"",
    mime: str = "",
    size: int | None = None,
    display_to: str = "",
) -> bytes:
    props: list[tuple] = []
    streams: list[tuple[str, bytes, str | None]] = []
    if subject:
        props.append((0x0037, 0x001F))
        streams.append(("__substg1.0_0037001F", subject.encode("utf-16-le"), None))
    if body:
        props.append((0x1000, 0x001F))
        streams.append(("__substg1.0_1000001F", body.encode("utf-16-le"), None))
    if html:
        props.append((0x3FDE, 0x0003, struct.pack("<I", 65001)))
        props.append((0x1013, 0x0102))
        streams.append(("__substg1.0_10130102", html.encode("utf-8"), None))
    if rtf:
        props.append((0x1009, 0x0102))
        streams.append(("__substg1.0_10090102", rtf, None))
    if display_to:
        props.append((0x0E04, 0x001F))
        streams.append(("__substg1.0_0E04001F", display_to.encode("utf-16-le"), None))
    streams.insert(0, ("__properties_version1.0", _properties(32, *props), None))
    if filename:
        attach_props: list[tuple] = [(0x3707, 0x001F), (0x3701, 0x0102)]
        if mime:
            attach_props.append((0x370E, 0x001F))
        if size is not None:
            attach_props.append((0x0E20, 0x0003, struct.pack("<I", size)))
        streams.extend([
            ("__properties_version1.0", _properties(8, *attach_props), "attach"),
            ("__substg1.0_3707001F", filename.encode("utf-16-le"), "attach"),
            ("__substg1.0_37010102", _SECRET, "attach"),
        ])
        if mime:
            streams.append(("__substg1.0_370E001F", mime.encode("utf-16-le"), "attach"))
    return _cfb(streams)


def _properties(header: int, *items: tuple) -> bytes:
    counts = struct.pack("<8x4I", 0, 1 if header == 32 else 0, 0, 1 if any(item[0] == 0x3707 for item in items) else 0)
    head = (counts + b"\x00" * header)[:header]
    parts = []
    for item in items:
        pid, ptyp = item[0], item[1]
        payload = item[2] if len(item) > 2 else b"\x00" * 8
        parts.append(struct.pack("<HH", ptyp, pid) + b"\x00" * 4 + payload[:8].ljust(8, b"\x00"))
    return head + b"".join(parts)


def _cfb(streams: list[tuple[str, bytes, str | None]]) -> bytes:
    entries: list[tuple[str, int, bytes | None]] = [("Root Entry", 5, None)]
    for name, data, parent in streams:
        if parent == "attach" and entries[-1][0] != "__attach_version1.0_#00000000":
            entries.append(("__attach_version1.0_#00000000", 1, None))
        entries.append((name, 2, data))
    mini = 64
    blobs: list[bytes] = []
    starts: list[int] = []
    sizes: list[int] = []
    for _name, kind, data in entries:
        if kind != 2 or data is None:
            starts.append(_END)
            sizes.append(0)
            continue
        padded = data + b"\x00" * ((-len(data)) % mini)
        starts.append(len(blobs))
        sizes.append(len(data))
        blobs.extend(padded[index:index + mini] for index in range(0, len(padded), mini))
    mini_fat = [_FREE] * 128
    cursor = 0
    for _name, kind, data in entries:
        if kind != 2 or not data:
            continue
        count = (len(data) + mini - 1) // mini
        for step in range(count - 1):
            mini_fat[cursor + step] = cursor + step + 1
        mini_fat[cursor + count - 1] = _END
        cursor += count
    mini_stream = b"".join(blobs)
    sector = 512
    dir_sectors = (len(entries) * 128 + sector - 1) // sector
    mini_fat_sector = 1 + dir_sectors
    mini_stream_sector = mini_fat_sector + 1
    stream_sectors = max(1, (len(mini_stream) + sector - 1) // sector)
    fat = [_FREE] * 128
    fat[0] = _FAT
    for index in range(dir_sectors - 1):
        fat[1 + index] = 2 + index
    fat[dir_sectors] = _END
    fat[mini_fat_sector] = _END
    for step in range(stream_sectors - 1):
        fat[mini_stream_sector + step] = mini_stream_sector + step + 1
    fat[mini_stream_sector + stream_sectors - 1] = _END
    links = {sid: (_FREE, _FREE, _FREE) for sid in range(len(entries))}
    root_streams = [sid for sid, item in enumerate(entries) if sid and item[2] is not None and item[0] != "__attach_version1.0_#00000000" and _parent_of(entries, sid) is None]
    attach = next(sid for sid, item in enumerate(entries) if item[0] == "__attach_version1.0_#00000000") if any(item[0] == "__attach_version1.0_#00000000" for item in entries) else None
    chain = root_streams + ([attach] if attach is not None else [])
    if chain:
        links[0] = (_FREE, _FREE, chain[0])
        for left, right in zip(chain, chain[1:]):
            links[left] = (_FREE, right, links[left][2])
    if attach is not None:
        children = [sid for sid in range(attach + 1, len(entries))]
        if children:
            links[attach] = (_FREE, _FREE, children[0])
            for left, right in zip(children, children[1:]):
                links[left] = (_FREE, right, _FREE)
    directory = bytearray(dir_sectors * sector)
    for sid, (name, kind, _data) in enumerate(entries):
        left, right, child = links[sid]
        start = mini_stream_sector if sid == 0 else starts[sid]
        size = len(mini_stream) if sid == 0 else sizes[sid]
        directory[sid * 128:(sid + 1) * 128] = _entry(name, kind, 1, left, right, child, start, size)
    header = bytearray(512)
    header[0:8] = bytes.fromhex("D0CF11E0A1B11AE1")
    struct.pack_into("<H", header, 0x18, 0x003E)
    struct.pack_into("<H", header, 0x1A, 3)
    struct.pack_into("<H", header, 0x1C, 0xFFFE)
    struct.pack_into("<H", header, 0x1E, 9)
    struct.pack_into("<H", header, 0x20, 6)
    struct.pack_into("<I", header, 0x2C, 1)
    struct.pack_into("<I", header, 0x30, 1)
    struct.pack_into("<I", header, 0x38, 4096)
    struct.pack_into("<I", header, 0x3C, mini_fat_sector)
    struct.pack_into("<I", header, 0x40, 1)
    struct.pack_into("<I", header, 0x44, _END)
    struct.pack_into("<I", header, 0x4C, 0)
    for index in range(1, 109):
        struct.pack_into("<I", header, 0x4C + 4 * index, _FREE)
    mini_padded = mini_stream + b"\x00" * ((-len(mini_stream)) % sector)
    if not mini_padded:
        mini_padded = b"\x00" * sector
    return bytes(header) + struct.pack("<128I", *fat) + bytes(directory) + struct.pack("<128I", *mini_fat) + mini_padded


def _parent_of(entries, sid: int) -> str | None:
    for index in range(sid, 0, -1):
        if entries[index][1] == 1:
            return entries[index][0]
    return None


def _entry(name: str, kind: int, color: int, left: int, right: int, child: int, start: int, size: int) -> bytes:
    raw = name.encode("utf-16-le") + b"\x00\x00"
    buf = bytearray(128)
    buf[:len(raw)] = raw
    struct.pack_into("<H", buf, 64, len(raw))
    buf[66] = kind
    buf[67] = color
    struct.pack_into("<III", buf, 68, left, right, child)
    struct.pack_into("<I", buf, 116, start & 0xFFFFFFFF)
    struct.pack_into("<Q", buf, 120, size)
    return bytes(buf)
