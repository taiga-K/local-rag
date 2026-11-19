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

スタックを上げて JSONL を入れるコマンドは1つである。

```bash
scripts/load-corpus.sh samples/corpus.jsonl bench
```

`samples/corpus.jsonl` の `externalRecordId` は `doc.weather_1` と `A._~:z-1` である。後者は `^[A-Za-z0-9][A-Za-z0-9._~:-]{0,255}$` に入る。先頭が `-` の id は 400 `ENVELOPE_INVALID` である。

ハーネスはそのあと次のボディで検索する。

```bash
curl -s -X POST http://127.0.0.1:43123/api/v1/retrieve \
  -H 'content-type: application/json' \
  -d '{"query":"東京の天気","limit":10,"rewriteQuery":false,"maxChunksPerRecord":1,"filters":{"kb":["bench"]}}'
```

完了を待つときは `GET /api/v1/kb/bench/indexing/counts` の `QUEUED` と `IN_PROGRESS` が 0 になるまで見る。各チャンクの `record.recordId` は push した `externalRecordId` である。

ハーネスは次の 2 つを使う。

1. `POST /api/v1/kb/{kb_id}/records`。`mimeType` は `application/blocks`、`blocksFormat` は 1、テキストブロックを置く。`externalRecordId` は `^[A-Za-z0-9][A-Za-z0-9._~:-]{0,255}$` である。
2. `POST /api/v1/retrieve`。ボディは `{"query","limit","rewriteQuery":false,"maxChunksPerRecord":1,"filters":{"kb":["<kb_id>"]}}` である。各チャンクの `record.recordId` は、その push の `externalRecordId` である。該当が無ければ `{"chunks":[],"incomplete":false}` である。

`kbindex-ingest load` は同じ push を JSONL から繰り返す。完了は `GET /api/v1/kb/{kb_id}/indexing/counts` の `QUEUED` と `IN_PROGRESS` が 0 になるまで待つ。

ベクトルストアの作り直しは既定で止まっている。有効にするには API の環境変数 `ENABLE_VECTOR_STORE_REBUILD=true` を置いて起動し直す。そのあと、空のコレクションに戻すのは `POST /api/v1/connectors/vector-store/cleanup`、保存済み本文から埋め直すのは `POST /api/v1/connectors/vector-store/reindex` である。点が残っているあいだモデル名の変更は 400 で、自動では入れ直さない。

`scripts/measure.py` は `--run` を付け、API が応答するときだけ計測する。付けないときは終了コード 2 で、時間は出さない。

融合は RRF だけである。式は Qdrant の `1/(position+2)`（position は 0 始まり）で、設定では変えない。キーワードは fastembed の `Qdrant/bm25` だけである。

BM25 の文書頻度と文書数は取り込みのたびに差分で更新する。検索はその差分を畳み込み済みの値に足す。差分を畳み込むのは `kbindex-maintain fold`、postings から数え直すのは `kbindex-maintain recount` である。このプロセスは常駐させない。

この版へ上げたあとは、一度 `kbindex-maintain recount` を実行する。起動時の移行は表とトリガーを作り、既存の `(generation, tokenizer)` を `bm25_df_pending` に載せるだけで、recount はしない。pending のあいだ、文書頻度だけ postings を数える。文書数は `bm25_stats.doc_count` と `bm25_count_delta` の和である。recount が終わると pending は消える。

索引の状態は `GET /api/v1/knowledgeBase/record/{recordId}` と `GET /api/v1/records/{recordId}` が返す。件数は `GET /api/v1/connectors/{kbId}/stats` の `data.stats.indexingStatus` である。再処理は `POST /api/v1/records/{recordId}/reindex` である。

## テスト

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest
```

`pytest` は単体テストだけを実行する。`INTEGRATION=1 pytest` は compose の Postgres、Redis、Qdrant を使う。`SLOW=1 pytest` は `ruri-v3-310m` を 1 回ロードする。

`DESIGN.md` の未決は残っていない。テストの割り当ては `TEST_DESIGN.md` にある。依存の版と SPDX は `THIRD_PARTY.md` にある。

文字バイグラムの既定は NFKC、空白と制御文字を除く、大小と句読点は残す。`bm25.k1` は 1.2、`bm25.b` は 0.75 である。`keyword.char_bigram.casefold`、`drop_punct`、`bm25.k1`、`bm25.b` はベンチマークの調整候補である。`redis.lanes` の既定は 1 である。PipesHub の既定 8 にするときはこの値を 8 にして API とワーカーを起動し直す。
