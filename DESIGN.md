# ローカル検索の設計

参照コミットは [pipeshub-ai/pipeshub-ai@7aff0de37be83beac220e801b83e303bd4018911](https://github.com/pipeshub-ai/pipeshub-ai/tree/7aff0de37be83beac220e801b83e303bd4018911) である。この文書は実装の契約である。コードよりこちらを優先する。

要件アーカイブ `uploads/rag_research.tar.gz` は、この実行環境のディスクに存在しなかった。`/workspace/uploads/rag_research.tar_3111.gz` は Read が拡張子で拒否し、シェルからはパス自体が見えなかった。したがって `rag_requirements.md` ほかのノートは未読である。オーナーの依頼文と、上記コミットのソースで決まっていることだけを採用する。ノートにしか無い判断は「未決」に置く。

LLM は置かない。回答生成、クエリ書き換え、分類、固有表現抽出はしない。

## 名前

プロセスは1つの Python パッケージ `kbindex` である。API とワーカーは同じイメージで、コマンドだけ分ける。知識ベースを `kb`、投入された1件を `record`、投入ブロックを `block`、埋め込み単位を `chunk` と呼ぶ。

## データ形

外部入力は境界でだけ検証する。境界の内側は次の形だけを渡す。

`KbId` と `ExternalRecordId` は別の型である。どちらも文字列だが、混ぜない。

`ExternalRecordId` は `^[A-Za-z0-9][A-Za-z0-9._~:-]{0,255}$` の全文一致である。PipesHub の `EXTERNAL_RECORD_ID_PATTERN` と同じである。

`RecordId` は UUID である。値は `uuid5(NAMESPACE, kb_id + "\x1f" + external_record_id)` で、`NAMESPACE` は `c3a1e5b0-7d2e-4b1a-9f60-4a0b1c2d3e4f` に固定する。PipesHub は org を含む別の UUID5 である（`push/service.py` の `push_record_key`）。このシステムに org は無いので、名前空間を分けて衝突を避ける。

`Version` は 0 以上 `2**53 - 1` 以下の整数である。真偽値は拒否する。

`ContentRev` は正規化バイト列の SHA-256 の先頭 16 桁（16進）である。`RevisionId` は `pb1:{digest64}:{contentRev}` である。digest の材料は PipesHub `contract.py` の `request_digest` と同じである。正規化タグ `pb1`、ブロックの正規 JSON の SHA-256、プロパティの正規 JSON を `0x1f` で区切って SHA-256 する。画像フィンガープリントは付けない。このシステムは画像を取得しない。

`IndexFingerprint` は次の文字列を改行でつないだ SHA-256 である。

- `embedding.model`
- モデルの `hidden_size` と、ロード後の `max_seq_length`
- `chunk.policy`（固定で `B`）
- `keyword.tokenizers` をソートした列
- `keyword.sudachi.mode` と `keyword.sudachi.normalize`
- `fusion.method` と `fusion.k`

`embedding.device` と BM25 の `k1` `b` はフィンガープリントに入れない。ベクトルの中身と転置索引の中身が変わらないからである。

### レコードの状態

状態は1つだけ持つ。次の列挙である。

`QUEUED`、`IN_PROGRESS`、`COMPLETED`、`FAILED`、`EMPTY`

PipesHub `ProgressStatus`（`backend/python/app/config/constants/arangodb.py`）のうち、このシステムが使うものである。ファイル種別拒否、パスワード、マルチモーダル、手動索引、一時停止は作らない。コネクタが無いからである。

遷移は次だけである。

| 現在 | 事象 | 次 |
| --- | --- | --- |
| なし | 新規 push で本文あり | `QUEUED` |
| なし | 新規 push でテキストが空 | `EMPTY` |
| `QUEUED` | ワーカーが取り出した | `IN_PROGRESS` |
| `IN_PROGRESS` | 索引に書けた | `COMPLETED` |
| `IN_PROGRESS` | テキストが空だと分かった | `EMPTY` |
| `IN_PROGRESS` | 索引に書けなかった | `FAILED` |
| `COMPLETED` `FAILED` `EMPTY` `QUEUED` | reprocess | `QUEUED` |
| `IN_PROGRESS` | reprocess | 拒否（409） |
| いずれか | 内容が変わる更新 | `QUEUED` |
| いずれか | 同じ内容の高い version（名前だけなど） | 状態は維持 |
| いずれか | delete | 行が消える |

`FAILED` は `failure_reason` を持つ。`COMPLETED` と `EMPTY` は理由を空にする。

起動時に `IN_PROGRESS` が残っていたら `QUEUED` に戻し、同じイベントを再投入する。前回の処理がどこで落ちても、次の実行は現在の行を見て同じ終状態に寄る。

### push の判定

既存行と要求の組で、動作は1つに決まる。PipesHub `KbPushService._decide`（`push/service.py` 455行付近）から、ゴミ箱と org と画像の分岐を除いたものである。

| 既存 | version | 内容 | 結果 |
| --- | --- | --- | --- |
| なし | 任意 | 任意 | 201 `created`。全置換の初期書き込み |
| あり | より小さい | 任意 | 409 `STALE_VERSION` |
| あり | 等しい | 同じ digest | 200 `unchanged`。書き込まない |
| あり | 等しい | 違う digest | 409 `VERSION_CONFLICT` |
| あり | より大きい | 同じブロック digest | 200 `updated`。`contentChanged` は false。名前とメタデータと version だけ更新し、再索引しない |
| あり | より大きい | 違うブロック | 200 `updated`。`contentChanged` は true。保存バイトを置換し `QUEUED` |

削除した id は行が無い。同じ id の再 push は新規である。PipesHub のゴミ箱（409 `RECORD_IN_TRASH`）は採用しない。

## HTTP

プレフィックスは `/api/v1` である。認証は無い。

エラーボディは PipesHub `push/api.py` の `error_body` に合わせる。

```json
{"error": {"code": "HTTP_CONFLICT", "reason": "STALE_VERSION", "message": "...", "currentVersion": 7}}
```

`location` と `issues` と `limitBytes` は、あるときだけ付ける。`issues` は最大 50 件である。HTTP ステータスと `code` の対応は `push/api.py` の `_CODES` と同じである。`400` は `HTTP_BAD_REQUEST`、`409` は `HTTP_CONFLICT`、`413` は `HTTP_PAYLOAD_TOO_LARGE`、`415` は `HTTP_UNSUPPORTED_MEDIA_TYPE`、`422` は `HTTP_UNPROCESSABLE_ENTITY`、`503` は `HTTP_SERVICE_UNAVAILABLE` である。

### 知識ベース

`POST /api/v1/kb`

```json
{"id": "demo", "name": "demo"}
```

`id` を省略すると UUID を採る。同じ `id` が既にあれば 200 で既存を返す。新規は 201 である。`id` の文字種は `ExternalRecordId` と同じである。

`GET /api/v1/kb/{kb_id}` は 200 か 404 `KB_NOT_FOUND` である。

### push

`POST /api/v1/kb/{kb_id}/records`

PipesHub のルートは `kb_router.py` の `kb_push_router.post("/{kb_id}/records")` で、プレフィックスは `/api/v1/kb` である。

HTTP の `Content-Type` は `application/json` を受け付ける。これは `push/admission.py` の検査である。依頼文の `application/blocks` も受け付ける。それ以外は 415 `UNSUPPORTED_MEDIA_TYPE` である。レコードの `mimeType` フィールドは常に `application/blocks` である。

ボディ上限は 16 MiB である（`MAX_BODY_BYTES`）。超えたら 413 `PAYLOAD_TOO_LARGE` と `limitBytes` である。`Content-Length` が整数でなければ 400 `INVALID_CONTENT_LENGTH` である。

JSON として壊れていれば 400 `INVALID_JSON` である。未知キー、型の不一致、範囲外で、場所が `blocks` と `metadata` 以外なら 400 `ENVELOPE_INVALID` である。`blocks` なら 422 `BLOCKS_INVALID` である。`metadata` の値なら 422 `PROPERTY_INVALID` である。`issues[].location` は `blocks[0].data` のように pydantic の位置からタグ名を除いたものである（`format_location`）。

DTO は閉じた許容リストである。`extra` は拒否、数値と真偽は厳密である。`"5"` は整数ではない。`1` は真偽値ではない。`true` は version でも `blocksFormat` でもない。空の配列、空のオブジェクト、既定値だけの部分オブジェクト、省略は、正規化では同じ欠如である。ただし `blocks` 自体と `metadata.values` の空オブジェクトは残す。フィールド順は宣言順で、正規 JSON の一部である。

封筒のフィールドは次である。

| フィールド | 必須 | 形 |
| --- | --- | --- |
| `recordName` | はい | 1 から 255 文字。前後の空白は除く。空なら拒否。HTML タグと printf 指定子は拒否 |
| `mimeType` | はい | `"application/blocks"` だけ |
| `externalRecordId` | はい | 上記のパターン |
| `version` | はい | 上記の整数 |
| `blocksFormat` | はい | `1` だけ |
| `sourceLastModifiedTimestamp` | いいえ | 1 以上の整数（ミリ秒） |
| `metadata` | いいえ | 下記 |
| `blocks` | はい | 下記。空のコンテナも合法 |

`metadata.schemaId` は 1 から 300 文字である。`metadata.values` は最大 256 件である。キーは 64 文字までである。値は、短い文字列（1024 文字まで）、厳密な真偽値、厳密な整数、有限の小数、短い文字列の配列（最大 64）、または JSON の null である。null は保存時に欠く。`schemaId` があるとき、その知識ベースに同じ id のスキーマが無ければ 422 `SCHEMA_NOT_FOUND` である。形は PipesHub が `orgId:kbId:version` であることを要求する（`service.py` `_load_schema`）。このシステムに org は無いので、`schemaId` は `PUT` で登録した文字列と完全一致すればよい。不一致の規則そのものは残す。

ブロックとグループに `id` は無い。送ると 422 である。索引が UUID を振る。

ブロックの `type` は `text`、`image`、`table_row` だけである。共通フィールドは `index`、`parent_index`、`type`、`sub_type`、`name`、`format`、`data`、`weburl`、`citation_metadata`、`list_metadata`、`table_row_metadata` である。`index` は 0 以上で、配列上の位置と一致する。`text` の `data` は 1 MiB 以下の文字列である。空文字は許す。`image.data.uri` は 1 文字以上、28 MiB 以下の文字列である。取得はしない。埋め込みもしない。`table_row.data` は `cells`（1 から 512 個の文字列）か `row_natural_language_text` の少なくとも一方を持つ。

グループの `type` は `text_section`、`list`、`ordered_list`、`table` だけである。子範囲は高々 1 回覆う。入れ子は 64 までである。65 は 422 である。ブロック数の上限は 100000、グループは 20000、1 グループの範囲は 1000、セルは 512 である。数は `contract.py` の定数と同じである。

`weburl` は http か https で、ホストがあり、2048 文字までである。

知識ベースが無ければ 404 `KB_NOT_FOUND` である。

成功ボディは `PushResult.to_json` と同じキーである。

```json
{
  "recordId": "...",
  "kbId": "demo",
  "externalRecordId": "doc-1",
  "version": 1,
  "status": "created",
  "contentChanged": true,
  "contentRev": "0123456789abcdef",
  "schemaId": null,
  "event": "newRecord",
  "indexingStatus": "QUEUED"
}
```

`status` は `created`、`updated`、`unchanged` である。`event` は新規が `newRecord`、内容更新が `updateRecord`、それ以外は null である。`unchanged` の `indexingStatus` は現在の状態を返す。

Postgres へ書けなければ 503 `POSTGRES_UNAVAILABLE` で、行は残さない。Redis へ流せなければ、行の書き込みを戻して 503 `REDIS_UNAVAILABLE` を返す。同じボディの再送は新規になる。Qdrant が止まっていても push は受け付ける。索引はワーカーが `FAILED` と理由 `QDRANT_UNAVAILABLE` にする。

フィンガープリントが保存済みの索引世代と違うとき、push は保存まで行うが `indexingStatus` を `QUEUED` のままにし、`event` は出さない。検索は 409 `INDEX_CONFIG_MISMATCH` である。`POST /api/v1/index/reindex` が世代を切り替え、全部を `QUEUED` に戻してから流す。

### スキーマ

`PUT /api/v1/kb/{kb_id}/schema` と `GET /api/v1/kb/{kb_id}/schema` を置く。push の `metadata` が 422 を返すために必要だからである。PipesHub は同じパスである（`kb_router.py` の `put_kb_schema`）。

ボディは `{ "schemaId": "notes", "properties": [ { "name": "lang", "type": "string" } ] }` である。`type` は `string`、`integer`、`number`、`boolean`、`string_list` だけである。未知キーは 400 である。登録は置換である。

PipesHub の `PropertyDefinition` にある `filterable` や `semanticLabel` は保存しない。検索フィルタは日付と `kbId` だけだからである。これは逸脱である。

### 削除

`DELETE /api/v1/kb/{kb_id}/records/{external_record_id}`

存在するなら 200 `{"deleted": true, "recordId": "...", "externalRecordId": "..."}` である。無ければ 404 `RECORD_NOT_FOUND` である。行、保存ファイル、チャンク、Qdrant の点、BM25 のポスティングを消す。`deleteRecord` を流す。ワーカーは点を書く直前に行の存在を見て、消えていれば自分の点も消す。

### 索引の観察

ノート `ingest_inspection_ui.md` は未読である。PipesHub の画面が実際に読んでいるのは、レコードの `indexingStatus` と失敗理由、およびステータス別件数である（`frontend/app/(main)/knowledge-base/components/kb-list-view.tsx` と `backend/python/app/api/routes/local_repos.py` の `_indexing`）。パス文字列はノートにしか無い可能性があるので、未決に残す。実装は次のパスでその項目を返す。ノートが別パスを指定していたら、パスだけ合わせる。

`GET /api/v1/kb/{kb_id}/records/{external_record_id}`

```json
{
  "recordId": "...",
  "externalRecordId": "doc-1",
  "version": 2,
  "indexingStatus": "FAILED",
  "failureReason": "QDRANT_UNAVAILABLE",
  "contentRev": "...",
  "updatedAt": "2026-11-17T00:00:00Z"
}
```

`GET /api/v1/kb/{kb_id}/indexing/counts`

```json
{"QUEUED": 0, "IN_PROGRESS": 0, "COMPLETED": 1, "FAILED": 0, "EMPTY": 0}
```

`POST /api/v1/kb/{kb_id}/records/{external_record_id}/reprocess`

`IN_PROGRESS` は 409 `IN_PROGRESS` である。それ以外の現状態は `QUEUED` にし、`failureReason` を空にし、`reprocess` を流して 202 を返す。無ければ 404 である。

`POST /api/v1/index/reindex` は世代を現在の設定で置き、Qdrant コレクションと BM25 を空にし、全文のあるレコードを `QUEUED` にして流す。202 と `{"fingerprint": "...", "queued": N}` を返す。

### 検索

`POST /api/v1/retrieve`

PipesHub は `app/api/routes/search.py` の `RetrieveQuery` と `POST /retrieve` である。要求のキーは同じである。

| フィールド | 既定 | 制約 |
| --- | --- | --- |
| `query` | 必須 | 1 文字以上。空白だけは 400 |
| `limit` | 8 | 1 から 50 |
| `filters` | `{}` | オブジェクト。使えるキーは `kbId` だけ。他のキーは 400 |
| `createdAfter` `createdBefore` `modifiedAfter` `modifiedBefore` | なし | `YYYY-MM-DD` またはオフセット付き ISO 8601。両端を含む |
| `maxChunksPerRecord` | なし | 1 から 50 |
| `rewriteQuery` | false | true は 400 `REWRITE_DISABLED` |

権限フィルタ、ユーザー、コネクタ許可は無い。日付が壊れていれば 400 である。

フィンガープリントが不一致なら 409 `INDEX_CONFIG_MISMATCH` である。Qdrant が落ちていれば 503 `QDRANT_UNAVAILABLE` である。Postgres が落ちていれば 503 `POSTGRES_UNAVAILABLE` である。

成功は 200 である。

```json
{
  "chunks": [
    {
      "id": "{recordId}:{blockIndex}:{piece}",
      "text": "...",
      "score": 0.0327,
      "record": {
        "recordId": "...",
        "name": "案内",
        "connector": "demo",
        "mimeType": "application/blocks",
        "updatedAt": 1700000000000
      },
      "citation": {
        "url": null,
        "recordUrl": null,
        "pageNum": null,
        "blockIndex": 0
      }
    }
  ],
  "incomplete": false
}
```

`score` は RRF の値である。`connector` は知識ベース id である。PipesHub のコネクタ名に相当する枠だけ残す。ヒットが無ければ `chunks` は空で 200 である。`incomplete` は、キーワード側かベクトル側の一方が失敗したときに true である。両方失敗なら 503 である。

`maxChunksPerRecord` があるとき、融合後の列からレコードごとにその件数まで残し、その後 `limit` で切る。

### デバッグ

画面は作らない。

`GET /api/v1/debug/kb/{kb_id}/records/{external_record_id}`

受け取った正規化前の生 JSON、正規化バイト、できたチャンク（`chunkId`、`text`、`blockIndex`、`piece`、`tokenCount`）を返す。

`POST /api/v1/debug/retrieve`

`/retrieve` と同じ要求である。応答は `/retrieve` の本体に `breakdown` を足す。各要素は、融合に入れたチャンクについて、`dense` の `rank` と `score`、トークナイザごとの `rank` と `score`、`rrf` である。そのリストに無い脚は null である。`rank` は 1 始まりである。件数は融合候補の上位 50 までである。

### ベンチマーク用の入口

外部ハーネスは次の2つだけを使う。

1. `POST /api/v1/kb/{kb_id}/records` を1件ずつ、または CLI `kbindex-ingest load`
2. `POST /api/v1/retrieve`

まとめて入れる HTTP は作らない。ハーネスは push の成功ボディの `indexingStatus` ではなく、`GET .../indexing/counts` の `QUEUED` と `IN_PROGRESS` が 0 になるまで待つ。

## 保存

### Postgres

グラフとメタデータと BM25 の転置索引を同じデータベースに置く。グラフは実体リンクの表である。固有表現の節点は作らない。

`knowledge_bases(id, name, created_at)`

`schemas(kb_id, schema_id, properties jsonb, primary key (kb_id, schema_id))`

`records`

- `record_id` uuid 主キー
- `kb_id`、`external_record_id` は一意
- `version`、`revision_id`、`content_rev`、`blocks_sha`
- `record_name`、`source_modified_ms`
- `indexing_status`、`failure_reason`
- `raw_path`（受け取ったボディのファイル）
- `stored_path`（正規化バイトのファイル）
- `created_at`、`updated_at`

`blocks(block_id uuid, record_id, position int, parent_position int, group_position int, type, text)`

`block_groups(record_id, position, parent_position, type, name)`

`chunks(chunk_id text primary key, record_id, block_id, block_index, piece, text, token_count)`

`chunk_id` は `{recordId}:{blockIndex}:{piece}` である。0 始まりの piece は、長いブロックを割ったときの通し番号である。

辺は表で表す。`record` が `block` を持ち、`block` が任意で `block_group` に属し、`chunk` が1つの `block` から出る。別のグラフ製品は置かない。

`index_generation(id int primary key default 1, fingerprint, model, dimension, max_seq_length, keyword_json, fusion_json, ready bool)`

行は常に1件である。

`bm25_stats(generation, tokenizer, doc_count, avgdl, total_tokens)`

`bm25_terms(generation, tokenizer, term, df, primary key (generation, tokenizer, term))`

`bm25_postings(generation, tokenizer, term, chunk_id, tf)`

トークナイザ名は `sudachi` と `char_bigram` である。索引は別々である。

### ファイル

PipesHub は push の正規化バイトをドキュメントストレージに置く（`test_kb_push_real_backends.py` の `storage.docs`）。ここはローカルディレクトリ `/data/records/{kb_id}/{record_id}.raw.json` と `.stored.json` である。置換は一時ファイルへ書いてから rename する。

### Qdrant

コレクション名は `chunks` である。PipesHub の `create_collection`（`services/vector_db/qdrant/qdrant.py`）に合わせる設定は次である。

- ベクトル名 `dense`
- 距離 cosine（`CollectionConfig.distance_metric` の既定）
- 次元はモデルの `hidden_size`。`cl-nagoya/ruri-v3-310m` の config は 768 である（2026-11-17 に Hugging Face の `config.json` を取得して確認した）
- `on_disk` のベクトルと HNSW は true
- 量子化は scalar
- `optimizers_config.default_segment_number` は 8

疎ベクトルは作らない。PipesHub の疎ベクトルは fastembed の BM25 である（`CollectionConfig.enable_sparse`）。キーワード側は Sudachi と文字バイグラムの別索引に置き換える。これは逸脱である。

ペイロードは `chunkId`、`recordId`、`kbId`、`blockIndex`、`piece`、`text`、`recordName`、`mimeType`、`sourceModifiedMs` である。

モデルを変えると次元が変わり得る。世代が違うあいだは検索しない。reindex はコレクションを削除して作り直す。

### Redis Streams

ストリーム名は `record-events` である。PipesHub の Redis Streams 実装が使う話題名と同じである（`services/messaging/redis_streams/indexing_consumer.py` のレーン `record-events.N`）。レーン分割はしない。消費者グループは `indexing` である。

フィールドは文字列である。

- `eventType`: `newRecord`、`updateRecord`、`reprocess`、`deleteRecord`
- `recordId`
- `kbId`
- `externalRecordId`
- `version`
- `contentRev`

ワーカーはグループで読み、処理のあと XACK する。再配送は同じ終状態に寄る。`version` が行より古ければ ACK して捨てる。`deleteRecord` のあと行が無ければ、その `recordId` の点とポスティングを消して ACK する。

Redis のイメージは 7.2 系に固定する。7.2 は BSD-3-Clause である。7.4 以降の RSALv2 と SSPL は使わない。

## チャンク

方針は PipesHub の `EMBED_POINT_POLICY=B` である（`vectorstore.py` の `_build_text_documents`）。1テキストブロックが1点である。ブロックがモデル窓より長ければ、モデルのトークナイザで境界を切り、重なりは無い。文分割と重なり窓は方針 A なので使わない。

窓の長さは、ロードした SentenceTransformer の `max_seq_length` である。`ruri-v3-310m` の `max_position_embeddings` は 8192 である。PipesHub のホストモデル向け既定 8191（`PIPESHUB_EMBED_TOKEN_LIMIT`）は、ローカルモデルの窓が読めるときは使わない（`_model_window`）。

空のテキストは点にしない。画像ブロックは点にしない。表の行は `cells` をタブ区切りにした文字列、それが無ければ `row_natural_language_text` を、テキストブロックと同じ規則で切る。

切った各片は同じ `blockIndex` を持ち、`piece` だけが増える。

## 埋め込み

既定の設定は次である。

```yaml
embedding:
  model: cl-nagoya/ruri-v3-310m
  device: cpu
keyword:
  tokenizers: [sudachi, char_bigram]
  sudachi:
    mode: C
    normalize: true
fusion:
  method: rrf
  k: 60
bm25:
  k1: 1.2
  b: 0.75
```

モデルのライセンスは Apache-2.0 である（モデルカード）。`device` は `cpu` または `cuda` だけである。クエリと文書で同じモデルを使う。前置句は付けない。モデルカードがクエリと文書で異なる前置を要求するかは未決である。カードの先は未読で、検索品質に効く。

## キーワード

Sudachi は分割モード C である。`normalize: true` のとき、語の表記は `normalized_form` である。false のとき `surface` である。品詞では落とさない。空文字の正規化形は捨てる。

文字バイグラムの定義は依頼文に無い。仮の規定を「未決」に書き、実装はその仮で動く。仮は、NFKC のあと、空白と制御文字を除いた符号点列の、隣り合う2点である。1点しか無ければ語は無い。

BM25 は Okapi である。`k1` と `b` は問い合わせ時の係数で、上の仮の既定を使う。転置索引は語と文書頻度と tf だけを持つ。

問い合わせも同じトークナイザにかける。トークナイザごとに順位リストを1本作る。密ベクトルの順位リストを加え、RRF で融合する。

`k` は 60 である。順位 `r` は 1 始まりで、寄与は `1 / (k + r)` である。リストに無い脚は 0 である。同じチャンクの寄与を足す。PipesHub のコレクション間 RRF は、重複ヒットに最大寄与だけを使う（`result_merging.py` の `ReciprocalRankFusionMerger`）。こちらは検索器が独立なので足す。Cormack の式である。`k` の既定値 60 は同じファイルの `DEFAULT_RRF_RANK_CONSTANT` である。

融合方式を `rrf` 以外にした設定は、起動時に拒否する。方式名の枠だけ残す。実装するのは `rrf` だけである。別方式は未決である。

## 取り込み CLI

コマンドは `kbindex-ingest` である。

`kbindex-ingest sync --kb demo --root ./samples --api http://127.0.0.1:43123`

`.txt` `.md` `.html` だけを見る。各ファイルを1レコードにする。`externalRecordId` は、根からの相対パスを、許される文字以外を `_` に替えたものである。`version` はファイルの mtime のナノ秒である。前回より時計が戻ったときは、CLI が前回 version に 1 を足した値をローカル台帳（`.kbindex-sync.json`）から使う。

`.txt` は1個の `text` ブロック、`format` は `txt` である。`.md` は見出しと段落を `text` ブロックにし、見出しの直前に `text_section` グループを置く。`.html` は段落、見出し、リスト項目を `text` ブロックにし、`script` と `style` は捨てる。どちらもブロックの `index` は位置と一致させる。

根に無くなったファイルは `DELETE` を呼ぶ。台帳にありディスクに無いものだけである。

`kbindex-ingest load --kb demo --jsonl corpus.jsonl` は、1行が `{"externalRecordId", "recordName", "text", "version"}` のファイルを push する。ベンチマークハーネスはこれを使う。

## 設定と起動

`docker compose up` は `postgres`、`redis`、`qdrant`、`api`、`worker` を上げる。API の公開ポートは 43123 である。埋め込みモデルは起動時に Hugging Face から取る。オフライン用に `HF_HOME` をボリュームにする。初回はネットワークが要る。

依存のライセンスは、実装の `THIRD_PARTY.md` に固定バージョンと SPDX を書く。商用不可のものは入れない。

## PipesHub との対応

| こちら | 参照 |
| --- | --- |
| push のパスと DTO と 400 と 422 | `backend/python/app/connectors/sources/localKB/push/contract.py`、`push/api.py`、`api/kb_router.py` |
| version と比較 | `push/service.py` `_decide`、`tests/integration/graph_db/test_kb_push_real_backends.py` |
| エラーコード表 | `push/api.py` `_CODES` |
| ボディ 16 MiB と Content-Type | `push/admission.py` |
| 状態名 | `config/constants/arangodb.py` `ProgressStatus` |
| 件数の見方 | `api/routes/local_repos.py` `_indexing` |
| チャンク方針 B | `modules/transformers/vectorstore.py` `_build_text_documents`、`_slice_on_character_boundaries` |
| Qdrant の作成引数 | `services/vector_db/qdrant/qdrant.py` `create_collection`、`services/vector_db/models.py` `CollectionConfig` |
| retrieve の要求とチャンク | `api/routes/search.py` `RetrieveQuery`、`_retrieve_chunks` |
| RRF の k=60 | `modules/retrieval/result_merging.py` |
| ストリーム名 | `services/messaging/redis_streams/indexing_consumer.py` |

## 逸脱

- 認証、権限フィルタ、リランカ、コネクタ、GCS、BigQuery、Kafka は無い。バスは Redis Streams だけである。PipesHub は Kafka と Redis Streams の両方を持つ。
- 削除は物理削除である。ゴミ箱は無い。
- org とユーザーは無い。`RecordId` の UUID5 材料が違う。
- 画像 URI は保存するだけである。`storage://` の実体化は無い。
- 疎ベクトルは作らない。キーワードは Postgres の BM25 である。
- `rewriteQuery: true` は 400 である。LLM が無い。
- スキーマのプロパティは型だけを見る。
- 融合は検索器ごとの和である。PipesHub のコレクション間融合は最大寄与である。
- HTTP の `application/blocks` も Content-Type として許す。PipesHub の検査は `application/json` だけである。

## 未決

要件ノートがディスクに無く、次はソースからも依頼文からも一意に決まらない。実装は仮を置くが、仮は要件ではない。

1. `rag_requirements.md`、`undecided_components.md`、`neo4j_vs_arangodb.md`、`embedding_switch_docs.md`、`japanese_support.md`、`rag_*_compare.md`、`kb_push_api.md`、`ingest_inspection_ui.md` の本文。アーカイブが届いたら、この文書と違う箇所はノートを優先して直す。
2. 索引観察 API のパス。ノートが別のパスを指定しているかもしれない。仮は「索引の観察」の3本である。根拠は、画面が見ているフィールドが状態と理由と件数であること（`kb-list-view.tsx`、`local_repos.py`）。選択肢は、仮のパスを維持する、ノートのパスに変える、PipesHub の知識ベース一覧クエリに寄せる、である。
3. 文字バイグラムの前処理。依頼文はトークナイザ名だけである。仮は NFKC のあと空白と制御文字を除いた隣接受符点である。選択肢は、生の符号点をすべて使う、空白だけ除く、Sudachi の語の中だけでバイグラムを切る、である。変わると再索引が要る。
4. `normalize: true` の意味。仮は Sudachi の `normalized_form` である。選択肢は、それ、`dictionary_form`、Unicode NFKC を表層に掛ける、である。
5. BM25 の `k1` と `b`。依頼文に無い。仮は 1.2 と 0.75 で、フィンガープリントには入れない。選択肢は、この仮、フィンガープリントに入れて再索引必須にする、である。係数は順位を変えるが転置索引の中身は変えない。
6. `ruri-v3-310m` のクエリ前置。モデルカードの使用例の続きは未読である。前置が必要なら、文書とクエリで同じ操作をしないと検索がずれる。選択肢は、前置なし（仮）、カードの指定に従う、である。
7. 融合方式を `rrf` 以外にしたときの意味。枠だけあり、実装は起動時に拒否する。選択肢は、拒否を維持する、方式を足して再索引必須にする、である。
8. 表の行を1点にまとめる PipesHub 方針 C を、方針 B の長いブロック分割と一緒に使うか。依頼文は方針 B だけを名指ししている。仮は行をテキストとして方針 B で切る。選択肢は、その仮、行をまとめない、方針 C の行グループを足す、である。
