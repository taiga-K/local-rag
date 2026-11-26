"""Readers for the light formats, the character-set order, and skip reasons."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import compressed_rtf
import pytest
from pydantic import TypeAdapter

from kbindex.blocks import document
from kbindex.contract import Block, Group, check_structure
from kbindex.cli import unreadable_paths_to_drop
from kbindex.formats import read_file
from kbindex.parse_csv import parse_csv
from kbindex.parse_html import parse_html
from kbindex.parse_json import parse_json
from kbindex.parse_md import parse_markdown
from kbindex.parse_msg import MSG_PARSE_TIMEOUT_SECONDS, _MAX_BYTES, _TEXT_CAP, _parts_of, _run_bounded, parse_msg
from kbindex.parse_plain import LOG_HARD_LIMIT_BYTES, LOG_MAX_BYTES, parse_capped
from kbindex.skip_reasons import ParseSkip, skip_message
from kbindex.text_decode import decode_text
from tests.unit.msg_pause import pause, ready, wide
from tests.unit.outlook_msg import sample_msg

BLOCKS = TypeAdapter(list[Block])
GROUPS = TypeAdapter(list[Group])


def _accept(body: dict) -> None:
    blocks = BLOCKS.validate_python(body["blocks"])
    groups = GROUPS.validate_python(body.get("block_groups") or [])
    check_structure(blocks, groups)


def test_shift_jis_txt_and_excel_csv_round_trip():
    sentence = "夜勤の引き継ぎは第三倉庫の鍵を使う"
    assert decode_text(sentence.encode("cp932")) == sentence
    csv_text = "品番,在庫\r\n品番 A-102 の在庫は 7 個,7\r\n"
    decoded = decode_text(csv_text.encode("cp932"))
    body = parse_csv(decoded, delimiter=",")
    _accept(body)
    assert body["blocks"][0]["citation_metadata"]["row_number"] == 2
    assert "品番 A-102 の在庫は 7 個" in body["blocks"][0]["data"]["row_natural_language_text"]


def test_bom_utf8_and_utf16():
    text = "朝礼は第一会議室"
    assert decode_text(b"\xef\xbb\xbf" + text.encode()) == text
    assert decode_text(b"\xff\xfe" + text.encode("utf-16-le")) == text


def test_markdown_table_list_and_code():
    body = parse_markdown("# 手順\n\n段落です。\n\n- 一つ\n\n```\ncode()\n```\n\n| 列 | 値 |\n| --- | --- |\n| 品番 | A-102 |\n")
    _accept(body)
    kinds = [block.get("sub_type") or block["type"] for block in body["blocks"]]
    assert "heading" in kinds
    assert "paragraph" in kinds
    assert "list_item" in kinds
    assert "code" in kinds
    row = next(block for block in body["blocks"] if block["type"] == "table_row")
    assert "列: 品番" in row["data"]["row_natural_language_text"]
    assert row["citation_metadata"]["row_number"] == 1


def test_html_skips_script_and_reads_table():
    body = parse_html("<h4>見出し</h4><script>fetch('http://example.test')</script><p>本文</p><ul><li>項目</li></ul><table><tr><th>列</th></tr><tr><td>値</td></tr></table>")
    _accept(body)
    texts = [block.get("data") if isinstance(block.get("data"), str) else block["data"].get("row_natural_language_text", "") for block in body["blocks"]]
    assert "本文" in texts
    assert all("fetch" not in item for item in texts)
    assert any(block["sub_type"] == "heading" for block in body["blocks"] if block["type"] == "text" and block.get("sub_type"))
    html_row = next(block for block in body["blocks"] if block["type"] == "table_row")
    assert html_row["citation_metadata"]["row_number"] == 1


def test_json_path_and_object_array():
    body = parse_json('{"倉庫": [{"品番": "A-102", "文言": "品番 A-102 の在庫は 7 個"}]}')
    _accept(body)
    row = body["blocks"][0]
    assert row["citation_metadata"]["section_title"] == "$.倉庫"
    assert "品番 A-102 の在庫は 7 個" in row["data"]["row_natural_language_text"]


def test_csv_keeps_every_row_and_two_regions(tmp_path: Path):
    lines = ["名前,数"] + [f"行{index},1" for index in range(501)]
    body = parse_csv("\n".join(lines) + "\n", delimiter=",")
    assert len(body["blocks"]) == 501
    two = parse_csv("a,b\n1,2\n\nc,d\n3,4\n", delimiter=",")
    assert len(two["block_groups"]) == 2


def test_log_keeps_head_and_tail_and_refuses_huge():
    payload = b"A" * (LOG_MAX_BYTES + 10) + b"Z"
    body = parse_capped(payload)
    assert "[省略]" in body["blocks"][0]["data"]
    assert body["blocks"][0]["data"].startswith("A")
    assert body["blocks"][0]["data"].endswith("Z")
    with pytest.raises(ParseSkip) as raised:
        parse_capped(b"x" * (LOG_HARD_LIMIT_BYTES + 1))
    assert raised.value.reason == "unreadable"


def test_epub_chapters_in_order():
    raw = _epub(["<p>第一章だけ</p>", "<p>第二章だけ</p>"])
    from kbindex.parse_epub import parse_epub

    body = parse_epub(raw)
    _accept(body)
    texts = [block["data"] for block in body["blocks"]]
    assert texts.index("第一章だけ") < texts.index("第二章だけ")


def test_broken_msg_is_skipped(tmp_path: Path):
    path = tmp_path / "note.msg"
    path.write_bytes(b"this is not an outlook file")
    with pytest.raises(ParseSkip) as raised:
        read_file(path)
    assert raised.value.reason == "unreadable"


def test_unknown_extension_is_unsupported(tmp_path: Path):
    path = tmp_path / "bundle.zip"
    path.write_bytes(b"not a real zip we care about")
    with pytest.raises(ParseSkip) as raised:
        read_file(path)
    assert raised.value.reason == "unsupported"
    assert skip_message("feature_required") == "追加機能が必要です"
    assert skip_message("models_missing") == "追加機能のモデルが未取得です"
    assert skip_message("scanned_pdf") == "スキャンPDFのため読めません"


def test_yaml_uses_the_json_flattener():
    from kbindex.parse_json import parse_yaml

    body = parse_yaml("場所: 第三倉庫\n")
    _accept(body)
    assert body["blocks"][0]["data"] == "第三倉庫"
    assert body["blocks"][0]["citation_metadata"]["section_title"] == "$.場所"


def _epub(chapters: list[str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("META-INF/container.xml", """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
<rootfiles><rootfile full-path="book.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>""")
        items = []
        spine = []
        for index, html in enumerate(chapters, start=1):
            name = f"c{index}.html"
            archive.writestr(name, f"<html><body>{html}</body></html>")
            items.append(f'<item id="c{index}" href="{name}" media-type="application/xhtml+xml"/>')
            spine.append(f'<itemref idref="c{index}"/>')
        archive.writestr("book.opf", f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
<manifest>{''.join(items)}</manifest>
<spine>{''.join(spine)}</spine>
</package>""")
    return buffer.getvalue()


def test_log_cut_stays_on_a_character_boundary():
    half = LOG_MAX_BYTES // 2
    content = "あ".encode() + b"A" * (half - 1) + "い".encode() + b"B" * LOG_MAX_BYTES
    text = parse_capped(content)["blocks"][0]["data"]
    assert "\ufffd" not in text
    assert text.startswith("あ")
    shifted = "亜".encode("cp932") + b"A" * (half - 1) + "井".encode("cp932") + b"B" * LOG_MAX_BYTES
    decoded = parse_capped(shifted)["blocks"][0]["data"]
    assert "\ufffd" not in decoded
    assert decoded.startswith("亜")


def test_message_without_text_is_skipped():
    with pytest.raises(ParseSkip) as raised:
        parse_msg(sample_msg(subject="", body="", filename=""))
    assert raised.value.reason == "unreadable"


def test_message_keeps_subject_body_and_attachment_name_only():
    body = parse_msg(sample_msg())
    texts = [block["data"] if isinstance(block["data"], str) else "" for block in body["blocks"]]
    joined = "\n".join(texts)
    assert "会議室の予約" in joined
    assert "本文は第四会議室の鍵箱に入っています" in joined
    assert "見積書.txt" in joined
    assert "SECRET-9F3C" not in joined
    assert all(text.strip() for text in texts)


def test_deleted_unreadable_path_is_dropped():
    assert unreadable_paths_to_drop(["gone.zip", "still.bin"], {"still.bin"}) == ["gone.zip"]


_REMOTE_HTML = """<html><body>
<p>倉庫の合言葉は青葉です</p>
<img src="https://example.invalid/secret-pixel.png" alt="図">
<img src="data:image/png;base64,AAAA">
<script>fetch("https://example.invalid/collect")</script>
<p style="background: url(https://example.invalid/bg.png)">近傍の文</p>
</body></html>"""


def test_html_message_drops_remote_images():
    raw = sample_msg(subject="画像つき", body="", filename="", html=_REMOTE_HTML, display_to="受付 <front@example.test>")
    parts = _parts_of(raw)
    assert "https://example.invalid" not in parts["body"]
    assert "data:image/png;base64,AAAA" in parts["body"]
    assert "fetch(" not in parts["body"]
    assert "倉庫の合言葉は青葉です" in parts["body"]
    body = parse_msg(raw)
    _accept(body)
    texts = _msg_text(body)
    assert "倉庫の合言葉は青葉です" in texts
    assert "front@example.test" in texts
    assert "example.invalid" not in texts
    assert all(block["type"] != "image" for block in body["blocks"])


def test_message_table_keeps_its_row_number():
    html_body = "<table><tr><th>列</th></tr><tr><td>値</td></tr></table>"
    body = parse_msg(sample_msg(subject="件名", body="", filename="", html=html_body))
    _accept(body)
    row = next(block for block in body["blocks"] if block["type"] == "table_row")
    assert row["citation_metadata"]["row_number"] == 1


def test_long_div_body_stays_within_the_block_cap(monkeypatch):
    assert _TEXT_CAP == 1 << 20
    monkeypatch.setattr("kbindex.parse_msg._TEXT_CAP", 4)
    body = parse_msg(sample_msg(subject="長い", body="", filename="", html="<div>仕切りの本文は青葉です</div>"))
    _accept(body)
    texts = [block["data"] for block in body["blocks"] if isinstance(block["data"], str)]
    assert texts[0] == "長い"
    assert all(len(item) <= 4 for item in texts)
    assert "青葉" in "".join(texts)


def test_message_keeps_text_that_is_not_in_a_paragraph():
    html_body = (
        "<html><body><div>仕切りの本文は青葉です</div>"
        "<span>範囲の本文は紅葉です</span><font>書体の本文は黄葉です</font></body></html>"
    )
    texts = _msg_text(parse_msg(sample_msg(subject="件名あり", body="", filename="", html=html_body)))
    assert "青葉" in texts
    assert "紅葉" in texts
    assert "黄葉" in texts


def test_html_body_wins_over_rtf_and_plain():
    raw = sample_msg(
        subject="",
        body="プレーンは使わない",
        filename="",
        html="<html><body><p>HTML本文の合言葉は朝顔です</p></body></html>",
        rtf=_encapsulated("RTFは使わない"),
    )
    texts = _msg_text(parse_msg(raw))
    assert "朝顔" in texts
    assert "プレーンは使わない" not in texts
    assert "RTFは使わない" not in texts


def test_encapsulated_rtf_wins_over_plain():
    raw = sample_msg(subject="", body="プレーンは使わない", filename="", rtf=_encapsulated("圧縮RTFの合言葉は青葉です"))
    texts = _msg_text(parse_msg(raw))
    assert "青葉" in texts
    assert "プレーンは使わない" not in texts


def test_plain_body_wins_over_rtf_text():
    raw = sample_msg(subject="", body="プレーン本文の合言葉は夕顔です", filename="", rtf=_plain_rtf("RTFは使わない"))
    texts = _msg_text(parse_msg(raw))
    assert "夕顔" in texts
    assert "RTFは使わない" not in texts


def test_rtf_text_is_used_when_nothing_else_is_present():
    raw = sample_msg(subject="", body="", filename="", rtf=_plain_rtf("RTFだけの本文は第五倉庫です"))
    texts = _msg_text(parse_msg(raw))
    assert "第五倉庫" in texts


def test_attachment_lists_type_and_size_not_bytes():
    raw = sample_msg(mime="text/plain", size=4096)
    texts = _msg_text(parse_msg(raw))
    assert "見積書.txt" in texts
    assert "text/plain, 4,096 bytes" in texts
    assert "SECRET-9F3C" not in texts


def test_oversized_message_is_skipped():
    with pytest.raises(ParseSkip) as raised:
        parse_msg(b"x" * (_MAX_BYTES + 1))
    assert raised.value.reason == "unreadable"


def test_slow_message_parse_is_skipped():
    assert MSG_PARSE_TIMEOUT_SECONDS == 60
    assert _run_bounded(ready, b"", MSG_PARSE_TIMEOUT_SECONDS) == "ready"
    page = _run_bounded(wide, b"", 15)
    assert page.startswith("あ") and len(page) == 200_000
    with pytest.raises(ParseSkip) as raised:
        _run_bounded(pause, b"", 0.8)
    assert raised.value.reason == "unreadable"


def _msg_text(body: dict) -> str:
    parts = []
    for block in body["blocks"]:
        data = block["data"]
        parts.append(data if isinstance(data, str) else str(data.get("row_natural_language_text") or ""))
    return "\n".join(parts)


def _rtf_text(text: str) -> bytes:
    parts = []
    for char in text:
        if " " <= char < "\x7f" and char not in "\\{}":
            parts.append(char)
        else:
            parts.append(f"\\u{ord(char)}?")
    return "".join(parts).encode("ascii")


def _encapsulated(sentence: str) -> bytes:
    raw = b"{\\rtf1\\ansi\\fromhtml1{\\*\\htmltag64 <p>}" + _rtf_text(sentence) + b"{\\*\\htmltag72 </p>}}"
    return compressed_rtf.compress(raw)


def _plain_rtf(sentence: str) -> bytes:
    raw = b"{\\rtf1\\ansi\\pard " + _rtf_text(sentence) + b"\\par}"
    return compressed_rtf.compress(raw)


def test_empty_document_helper():
    body = document([], [])
    assert body["blocks"][0]["index"] == 0
