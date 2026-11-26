"""Citation dicts are written as JSON text. Postgres rejects a bare dict."""

from kbindex.db import replace_graph, write_record_index


class _Conn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, text, params=None):
        self.calls.append((text, tuple(params or ())))


def test_replace_graph_casts_citation_json():
    conn = _Conn()
    replace_graph(conn, "rid", [(0, None, "table_row", "品番: A", {"row_number": 2})])
    inserts = [call for call in conn.calls if call[0].lstrip().startswith("insert into blocks")]
    sql, params = inserts[0]
    assert "%s::jsonb" in sql
    assert params[-1] == '{"row_number": 2}'


def test_replace_graph_leaves_a_missing_citation_null():
    conn = _Conn()
    replace_graph(conn, "rid", [(0, None, "text", "本文", None)])
    inserts = [call for call in conn.calls if call[0].lstrip().startswith("insert into blocks")]
    assert inserts[0][1][-1] is None


def test_write_record_index_keeps_an_encoded_citation():
    conn = _Conn()
    write_record_index(
        conn,
        "rid",
        {
            "blocks": [
                {
                    "block_id": "b",
                    "position": 0,
                    "parent_position": None,
                    "group_position": None,
                    "type": "table_row",
                    "text": "品番: A",
                    "citation": {"row_number": 2},
                }
            ],
            "groups": [],
            "chunks": [],
            "postings": [],
        },
    )
    inserts = [call for call in conn.calls if call[0].lstrip().startswith("insert into blocks")]
    assert inserts[0][1][-1] == '{"row_number": 2}'
