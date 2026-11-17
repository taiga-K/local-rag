# kbindex

日本語の文書を索引し、質問に近いチャンクを HTTP で返す。回答文は作らない。

## 起動する

```bash
docker compose up --build
```

API は `http://127.0.0.1:43123` で待つ。初回起動は `cl-nagoya/ruri-v3-310m` を Hugging Face から取る。`HF_HOME` はボリューム `hf` に残る。Redis のイメージは 7.2 系で、ライセンスは BSD-3-Clause である。

モデルを取らずに動かすときは `config.test.yaml` を使う。`embedding.backend` は `fake` である。

```bash
docker compose up -d postgres redis qdrant
DATABASE_URL=postgresql://kbindex:kbindex@127.0.0.1:54329/kbindex \
REDIS_URL=redis://127.0.0.1:63799/0 \
QDRANT_URL=http://127.0.0.1:46333 \
DATA_DIR=/tmp/kbindex-records \
KBINDEX_CONFIG=config.test.yaml \
kbindex-api
```

別の端末で `kbindex-worker` を同じ環境変数で起動する。

## サンプルを入れる

`samples/` には次の文がある。

- `weather.txt` は「東京都の今日の天気は晴れです。」
- `library.md` は「市立図書館は水曜が休館です。」
- `train.html` は「山手線は池袋で乗り換えます。」

```bash
kbindex-ingest sync --kb demo --root samples --api http://127.0.0.1:43123
```

`GET /api/v1/kb/demo/indexing/counts` の `QUEUED` と `IN_PROGRESS` が 0 になってから検索する。

```bash
curl -s -X POST http://127.0.0.1:43123/api/v1/retrieve \
  -H 'content-type: application/json' \
  -d '{"query":"東京の天気","filters":{"kb":["demo"]}}'
```

`limit` の既定は 10、上限は 10 である。 `filters.kb` は知識ベース id の配列である。

## ベンチマークの入口

ハーネスが使う入口は次の 2 つだけである。

1. `kbindex-ingest load --kb demo --jsonl corpus.jsonl --api http://127.0.0.1:43123`
   1 行は `{"externalRecordId","recordName","text","version"}` である。同じ投入は `POST /api/v1/kb/{kb_id}/records` を 1 件ずつ呼んでもよい。
2. `POST /api/v1/retrieve`

まとめて入れる HTTP は無い。完了は push の `indexingStatus` ではなく、`GET /api/v1/kb/{kb_id}/indexing/counts` の `QUEUED` と `IN_PROGRESS` が 0 になるまで待つ。

`scripts/measure.py` は `--run` を付け、API が応答するときだけ計測する。付けないときは終了コード 2 で、時間は出さない。

## テスト

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest
```

`pytest` は単体テストだけを実行する。`INTEGRATION=1 pytest` は compose の Postgres、Redis、Qdrant を使う。`SLOW=1 pytest` は `ruri-v3-310m` を 1 回ロードする。

未決の項目は `DESIGN.md` の「未決」にある。テストの割り当ては `TEST_DESIGN.md` にある。依存の版と SPDX は `THIRD_PARTY.md` にある。
