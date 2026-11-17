# kbindex

日本語の文書を索引し、質問に対するチャンクを HTTP で返す。回答文は作らない。LLM は使わない。

## 起動

```bash
docker compose up --build
```

API は `http://127.0.0.1:43123` である。初回は `cl-nagoya/ruri-v3-310m` を Hugging Face から取る。Redis は 7.2（BSD-3-Clause）である。

## サンプル

```bash
python -m kbindex.cli sync --kb demo --root samples --api http://127.0.0.1:43123
```

状態は `GET /api/v1/kb/demo/indexing/counts` で見る。`QUEUED` と `IN_PROGRESS` が 0 になってから検索する。

```bash
curl -s -X POST http://127.0.0.1:43123/api/v1/retrieve \
  -H 'content-type: application/json' \
  -d '{"query":"東京の天気","limit":10}'
```

## ベンチマークハーネス

ハーネスは次の2つだけを使う。

1. `POST /api/v1/kb/{kb_id}/records`  
   `Content-Type` は `application/json`。ボディは `blocksFormat: 1` の `application/blocks` である。`externalRecordId` と `version` で上書きする。同じ version で同じ内容は 200 `unchanged` である。
2. `POST /api/v1/retrieve`  
   `{"query":"...","limit":10,"filters":{"kb":["demo"]}}`。`limit` の既定は 10、上限は 10 である。

まとめて入れるときは CLI を使う。

```bash
python -m kbindex.cli load --kb demo --jsonl corpus.jsonl --api http://127.0.0.1:43123
```

1行は `{"externalRecordId","recordName","text","version"}` である。索引完了は counts の `QUEUED` と `IN_PROGRESS` が 0 になるまで待つ。

削除は `DELETE /api/v1/kb/{kb_id}/records/{externalRecordId}` である。

## テスト

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest
```

`pytest -m integration` は compose が要る。`pytest -m slow` は実モデルを1本だけロードする。

設計は `DESIGN.md`、テストの割り当ては `TEST_DESIGN.md` である。未決は `DESIGN.md` の「未決」にある。

## 計測

`scripts/measure.py` は起動中の API に対して索引時間と検索遅延を測る。数値は実行結果だけを出す。
