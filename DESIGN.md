# ローカル検索の設計

参照コミットは [pipeshub-ai/pipeshub-ai@7aff0de37be83beac220e801b83e303bd4018911](https://github.com/pipeshub-ai/pipeshub-ai/tree/7aff0de37be83beac220e801b83e303bd4018911) である。この文書は実装の契約である。コードよりこちらを優先する。

要件ノートは `uploads/` の個別ファイルとして読んだ。閉じた判断は末尾にまとめる。未決は残っていない。

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

指紋が保存済みと違い点が残っているとき、検索は 400 `INDEX_CONFIG_MISMATCH` である。`POST /api/v1/index/reindex` が世代を切り替え、全部を `QUEUED` に戻してから流す。

### スキーマ

`PUT /api/v1/kb/{kb_id}/schema` と `GET /api/v1/kb/{kb_id}/schema` を置く。push の `metadata` が 422 を返すために必要だからである。PipesHub は同じパスである（`kb_router.py` の `put_kb_schema`）。

ボディは `{ "schemaId": "notes", "properties": [ { "name": "lang", "type": "string" } ] }` である。`type` は `string`、`integer`、`number`、`boolean`、`string_list` だけである。未知キーは 400 である。登録は置換である。

PipesHub の `PropertyDefinition` にある `filterable` や `semanticLabel` は保存しない。検索で効くフィルタは日付と `filters.kb` だけだからである。これは逸脱である。

### 削除

`DELETE /api/v1/kb/{kb_id}/records/{external_record_id}`

存在するなら 200 `{"deleted": true, "recordId": "...", "externalRecordId": "..."}` である。無ければ 404 `RECORD_NOT_FOUND` である。行、保存ファイル、チャンク、Qdrant の点、BM25 のポスティングを消す。`deleteRecord` を流す。ワーカーは点を書く直前に行の存在を見て、消えていれば自分の点も消す。

### 索引の観察

`ingest_inspection_ui.md` は画面の項目（状態、失敗理由、状態別件数、再処理）を決める。パスは PipesHub に合わせた。記録画面が呼ぶ `GET /api/v1/knowledgeBase/record/{recordId}` と、Node が中継する先の `GET /api/v1/records/{recordId}` は同じ本体を返す。集計は `GET /api/v1/connectors/{kbId}/stats` である。再処理は `POST /api/v1/records/{recordId}/reindex` と、画面が先に呼ぶ `POST /api/v1/knowledgeBase/reindex/record/{recordId}` である。外部 id の GET、`GET /api/v1/kb/{kbId}/indexing/counts`、`POST .../reprocess` も残す。

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

`indexingStatus` が `IN_PROGRESS` のときだけ `embedDone` と `embedTotal` を付ける。PipesHub の知識ハブ行と同じ条件である（`knowledge_hub_service.py` の `_embed_progress`）。それ以外の状態ではこの2つを返さない。保存値が残っていても返さない。

`GET /api/v1/records/{recordId}` と `GET /api/v1/knowledgeBase/record/{recordId}` は次を返す。`record.indexingStatus` と `record.reason` が、画面が読む項目である。`reason` は上の `failureReason` と同じ値で、`COMPLETED` と `EMPTY` では null である。`IN_PROGRESS` のときだけ `embedDone` と `embedTotal` を `record` に付ける。無い id は 404 `RECORD_NOT_FOUND` である。org、権限、抽出段階は無い。

```json
{
  "record": {
    "id": "...",
    "recordName": "天気",
    "externalRecordId": "doc-1",
    "indexingStatus": "FAILED",
    "reason": "QDRANT_UNAVAILABLE",
    "version": 2
  },
  "knowledgeBase": {"id": "demo"}
}
```

`GET /api/v1/connectors/{kbId}/stats` は、知識ベースをコネクタ id として扱う。PipesHub の応答は `success` と `data.stats` である（`build_connector_stats_response`）。こちらは件数だけを返す。`extractionStatus` と `entitiesStatus` と `orgId` は付けない。分類と org が無いからである。未知の id は 404 `KB_NOT_FOUND` である。

```json
{
  "success": true,
  "data": {
    "connectorId": "demo",
    "origin": "COLLECTION",
    "stats": {
      "total": 1,
      "indexingStatus": {"QUEUED": 0, "IN_PROGRESS": 0, "COMPLETED": 1, "FAILED": 0, "EMPTY": 0}
    }
  }
}
```

`GET /api/v1/kb/{kb_id}/indexing/counts`

```json
{"QUEUED": 0, "IN_PROGRESS": 0, "COMPLETED": 1, "FAILED": 0, "EMPTY": 0}
```

`POST /api/v1/kb/{kb_id}/records/{external_record_id}/reprocess`

PipesHub に `reprocess` というルートは無い。GUI が呼ぶ再実行は `POST /api/v1/records/{record_id}/reindex` である（`connectors/api/router.py`）。同じ操作を、外部 id では上のパス、内部 `recordId` では `POST /api/v1/records/{record_id}/reindex` で受ける。ボディは空でよい。PipesHub の `depth` と `stages` は受け取っても無視する。分類と固有表現が無いからである。

`IN_PROGRESS` は 409 `IN_PROGRESS` である。それ以外の現状態は `QUEUED` にし、`failureReason` を空にし、`reindexRecord` を流して 202 を返す。無ければ 404 である。

`POST /api/v1/index/reindex` は世代を現在の設定で置き、Qdrant コレクションと BM25 を空にし、全文のあるレコードを `QUEUED` にして流す。202 と `{"fingerprint": "...", "queued": N}` を返す。

### 検索

`POST /api/v1/retrieve`

PipesHub は `app/api/routes/search.py` の `RetrieveQuery` と `POST /retrieve` である。要求のキーは同じである。

| フィールド | 既定 | 制約 |
| --- | --- | --- |
| `query` | 必須 | 1 文字以上。空白だけは 400 |
| `limit` | 10 | 1 から 10 |
| `filters` | `{}` | オブジェクト。PipesHub の公開キーは `apps`、`kb`、`recordGroups`、`records`、`recordsExact`、`entityFilters` である（`modules/retrieval/filter_schema.py`）。このシステムで結果を変えるのは `kb` だけである。値は知識ベース id の配列である。権限用のキー（`allowedApps` など）は受け取り、捨てる。それ以外の未知キーは 400 |
| `createdAfter` `createdBefore` `modifiedAfter` `modifiedBefore` | なし | `YYYY-MM-DD` またはオフセット付き ISO 8601。両端を含む |
| `maxChunksPerRecord` | なし | 1 から 50 |
| `rewriteQuery` | false | true は 400 `REWRITE_DISABLED` |

権限フィルタ、ユーザー、コネクタ許可は無い。日付が壊れていれば 400 である。

指紋が不一致で点が残っていれば 400 `INDEX_CONFIG_MISMATCH` である。メッセージは `POST /api/v1/index/reindex` を一つの操作として示す。Qdrant が落ちていれば 503 `QDRANT_UNAVAILABLE` である。Postgres が落ちていれば 503 `POSTGRES_UNAVAILABLE` である。

成功は 200 である。

```json
{
  "chunks": [
    {
      "id": "{recordId}:{blockIndex}",
      "text": "...",
      "score": 0.0327,
      "record": {
        "recordId": "doc-1",
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

`score` は RRF の値である。`connector` は知識ベース id である。PipesHub のコネクタ名に相当する枠だけ残す。`id` は PipesHub の `{virtualRecordId}:{blockIndex}` に合わせ、こちらでは `{recordId}:{blockIndex}` である（`search.py` の `_retrieve_chunks`）。同じブロックを複数片に割ったときは、2片目以降の `id` に `:{piece}` を足す。片が1つなら足さない。足さないと id が衝突する。ヒットが無ければ `chunks` は空で 200 である。`incomplete` は、キーワード側かベクトル側の一方が失敗したときに true である。両方失敗なら 503 である。

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

コレクション名は `records` である。PipesHub の単一コレクション戦略の既定名と同じである（`strategies/single.py`）。`create_collection`（`services/vector_db/qdrant/qdrant.py`）に合わせる設定は次である。

- ベクトル名 `dense`
- 距離 cosine（`CollectionConfig.distance_metric` の既定）
- 次元はモデルの `hidden_size`。`cl-nagoya/ruri-v3-310m` の config は 768 である（2026-11-17 に Hugging Face の `config.json` を取得して確認した）
- `on_disk` のベクトルと HNSW は true
- 量子化は scalar（INT8、quantile 0.95）
- `optimizers_config.default_segment_number` は 8
- HNSW の `ef_construct` は 256。検索時の `ef` は 256。量子化の oversampling は 1.5。`gui_settings_scope.md`（PipesHub `acc309552f12c960020431763c627040281717d1`）の表と、`qdrant.py` の `QDRANT_HNSW_EF_CONSTRUCT`、`qdrant/utils.py` の `QDRANT_HNSW_EF` と `QDRANT_OVERSAMPLING` である

疎ベクトルは作らない。PipesHub の疎ベクトルは fastembed の BM25 である（`CollectionConfig.enable_sparse`）。キーワード側は Sudachi と文字バイグラムの別索引に置き換える。これは逸脱である。

ペイロードは `chunkId`、`recordId`、`kbId`、`blockIndex`、`piece`、`text`、`recordName`、`mimeType`、`sourceModifiedMs` である。

指紋が保存済みと違い、Qdrant に点が残っているあいだ、検索は 400 `INDEX_CONFIG_MISMATCH` である。メッセージは、再索引するまで 400 のままであり、一つの操作は `POST /api/v1/index/reindex` だと書く。その操作がコレクションを消し、新しい指紋を記録し、全文のあるレコードを `QUEUED` にする。空のコレクションは新しい次元で作り直す。根拠は `embedding_switch_docs.md` と `gui_settings_scope.md` である。自動では入れ直さない。

### Redis Streams

ストリーム名は `record-events` である。消費者グループは `indexing` である。`redis.lanes` の既定は 1 である。PipesHub は `FAIR_SCHEDULING_LANE_COUNT` の既定を 8 にする（`services/messaging/config.py` L670、`acc3095`）。同じ関数の説明は、1 のときレーンを作らず、公開パスはレーン導入前の1本のままだと書いている（L651-L652）。消費者も 1 以下ならレーン数を記録しない（`indexing_consumer.py` L474-L475）。こちらはワーカーが1つで、コネクタごとの公平性で止める仕組みが無い。だから閉じた既定は、そのレーン無しの経路である。`redis.lanes` を 2 以上にすると、PipesHub の `RedisLaneRouter` と同じく `record-events.N` へ書き、消費者は基の `record-events` も読む（`lanes/hash_router.py` L84-L104）。レコード id の SHA-256 でレーンを決める（`stable_lane`、同ファイル L15-L33）。

メッセージは PipesHub の生産者と同じ封筒である（`redis_streams/producer.py`）。Redis のフィールドは `eventType`、`payload`、`timestamp` である。`payload` は JSON 文字列である。

`eventType` は `newRecord`、`updateRecord`、`deleteRecord`、`reindexRecord` である。`reindexRecord` は PipesHub の再索引イベント名である（`config/constants/arangodb.py`）。`payload` は `recordId`、`kbId`、`externalRecordId`、`version`、`contentRev` を持つ。

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
  char_bigram:
    nfkc: true
    casefold: false
    drop_space: true
    drop_control: true
    drop_punct: false
fusion:
  method: rrf
  k: 60
bm25:
  k1: 1.2
  b: 0.75
redis:
  lanes: 1
```

モデルのライセンスは Apache-2.0 である（モデルカード）。`device` は `cpu` または `cuda` だけである。文書には `検索文書: `、クエリには `検索クエリ: ` を付ける。モデルカード（`cl-nagoya/ruri-v3-310m` の README、2026-11-17 取得）がその2つを分けている。PipesHub の埋め込みサーバーは query と passage に同じ文字列を渡す（`japanese_support.md`）。こちらはカードに合わせる。接頭辞はフィンガープリントに入る。

## キーワード

Sudachi は分割モード C である。`normalize: true` のとき、語の表記は `normalized_form` である。false のとき `surface` である。品詞では落とさない。空文字の正規化形は捨てる。

文字バイグラムの既定は、NFKC のあと空白と制御文字（Unicode カテゴリ C）を除き、隣り合う符号点を語にする。大小は NFKC のまま残す。句読点は残す。1点しか無ければ語は無い。`keyword.char_bigram.casefold` と `drop_punct` はベンチマークが変えてよい。既定はどちらも false である。この5つの真偽はポスティングを変えるのでフィンガープリントに入る。変えたあとは `POST /api/v1/index/reindex` が要る。NFKC は全角ラテンを ASCII にするので、「ＡＢ」は「AB」になる。これは小文字化ではない。

文書の埋め込みには `検索文書: ` を、クエリには `検索クエリ: ` を付ける。

BM25 は Okapi である。`bm25.k1` の既定は 1.2、`bm25.b` の既定は 0.75 である。Okapi の標準であり、fastembed `Qdrant/bm25` の既定でもある（`fe_bm25_37c7.py`）。得点だけが変わり、語の集合は変わらない。フィンガープリントには入れない。ベンチマークの調整候補である。転置索引は語と文書頻度と tf だけを持つ。

問い合わせも同じトークナイザにかける。トークナイザごとに順位リストを1本作る。密ベクトルの順位リストを加え、RRF で融合する。

各枝は、融合の前に `limit * 2` 件を取る。`limit` は retrieve の件数である。PipesHub の Qdrant 検索は、dense の Prefetch と sparse の Prefetch がどちらも `req.limit * 2` である（`services/vector_db/qdrant/utils.py` L280-L301、`acc3095`）。こちらは密が1枝、Sudachi が1枝、文字バイグラムが1枝で、枝ごとに同じ深さである。疎ベクトルは作らない。融合はアプリ側で行う。Qdrant の `FusionQuery` は使わない。

`k` の既定は 60 である。順位 `r` は 1 始まりで、寄与は `1 / (k + r)` である。リストに無い脚は 0 である。同じチャンクの寄与を足す。PipesHub のコレクション間 RRF は、重複ヒットに最大寄与だけを使う（`result_merging.py` の `ReciprocalRankFusionMerger`）。こちらは検索器が独立なので足す。Cormack の式である。

`fusion.k` は設定値である。既定 60 のまま、`fusion.k: 2` にすると Qdrant サーバ既定との対照ができる。k はベクトルもポスティングも変えない。フィンガープリントには入れない。設定を変えて API とワーカーを起動し直せば足りる。再索引は要らない。

融合方式は RRF だけである。`fusion.method` が `rrf` 以外の設定は起動時に拒否する。方式名の枠は残す。DBSF も重み付き和も足さない。

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
| 融合前の候補深さ `max(limit * 2, 64)` | 起点は `services/vector_db/qdrant/utils.py` L280-L309（`acc3095`）の Prefetch `limit * 2`。下限 64 は下の「寝ている間の判断」 |
| RRF の式と、コレクション間の k=60 | `modules/retrieval/result_merging.py` の `DEFAULT_RRF_RANK_CONSTANT` |
| ストリーム名と封筒 | `services/messaging/redis_streams/indexing_consumer.py`、`redis_streams/producer.py`、`services/messaging/config.py` |
| 再索引ルート | `connectors/api/router.py` の `POST /records/{record_id}/reindex` |
| 状態別件数 | `connectors/api/router.py` の `GET /stats`、`services/graph_db/common/utils.py` の `build_connector_stats_response` |

## 逸脱

- 認証、権限フィルタ、リランカ、コネクタ、GCS、BigQuery、Kafka は無い。バスは Redis Streams だけである。PipesHub は Kafka と Redis Streams の両方を持つ。
- 削除は物理削除である。ゴミ箱は無い。
- org とユーザーは無い。`RecordId` の UUID5 材料が違う。
- 画像 URI は保存するだけである。`storage://` の実体化は無い。
- 疎ベクトルは作らない。キーワードは Postgres の BM25 である。
- `rewriteQuery: true` は 400 である。LLM が無い。
- スキーマのプロパティは型だけを見る。
- 融合は検索器ごとの和である。PipesHub のコレクション間融合は最大寄与である。
- dense とキーワードの RRF の k は 60 である。PipesHub が Qdrant に渡すハイブリッドは k を付けない。Qdrant v1.15 の既定は 2 で、式は `1/(position+2)`、position は 0 始まりである（`fusion_methods.md`）。k=60 は後段のコレクション間マージと、OpenSearch と Redis の値である。承認済み要件がこちらの融合に 60 を指定しているので、既定は 60 のままにする。対照は `fusion.k: 2` である。
- 候補の深さの起点は PipesHub の Prefetch `limit * 2` である。k=60 で密順位が 20 を超える文書が上位 10 から落ちるので、下限 64 を足した。融合の場所は違う。PipesHub は Qdrant サーバの Prefetch 2 本（dense と sparse）で融合する。こちらは密を Qdrant から、キーワードを Postgres の BM25 から取り、アプリ側で足す。キーワード枝は Sudachi と文字バイグラムの 2 本である。BM25 の候補は `filters.kb` で切ってから上位 N を取る。文書頻度は全体のままである。
- HTTP の `application/blocks` も Content-Type として許す。PipesHub の検査は `application/json` だけである。
- Redis のレーン既定は 1 である。PipesHub の環境変数既定は 8 である。1 は PipesHub が「レーン無し」と書く経路である。
- 表の行は方針 B のまま1点にする。PipesHub は方針 C で行をまとめる。

## ノートで閉じた判断

`rag_requirements.md`（taiga、2026-11-18 承認）が次を決めている。Sudachi モード C と `normalize: true`、RRF の k=60、チャンク方針 B、リランカ無し、Qdrant、Postgres、Redis Streams、ruri-v3-310m、モデル変更とキーワード方式の変更は全件入れ直し。`normalize: true` は Sudachi の `normalized_form` とする。`rag_sparse_compare.md` の表 A が「Sudachi C 単位 内容語＋正規化形」をその名前で測っている。内容語への絞り込みはノートが決めていないので、品詞では落とさない。

`gui_settings_scope.md`（PipesHub `acc3095`）が次を決めている。HNSW `ef` 256、oversampling 1.5、検索画面の件数 10。retrieve の上限は、この依頼が「既定 10、上限 10」と指定したので 10 にする。PipesHub の `RetrieveQuery` 自体は既定 8、上限 50 である（`search.py`）。埋め込みモデルは、点が残っているあいだ変更できない（`embedding_switch_docs.md`）。

`fusion_methods.md` が次を決めている。PipesHub が使う融合は RRF だけである。`Fusion.DBSF`、重み付き和、方式の切り替えは無い。`qdrant/utils.py` L304-L309（`acc3095`、`7aff0de` も同じ行）は `Fusion.RRF` を固定し、k を渡さない。`FusionMethod` の `ARITHMETIC_MEAN` と `HARMONIC_MEAN` は参照が無い。索引観察のパスも、同じノート群の `ingest_inspection_ui.md` が画面の呼ぶ先を書いているので、上のパスで閉じた。

ruri-v3 の接頭辞はモデルカードで閉じた。文書は `検索文書: `、クエリは `検索クエリ: ` である（`cl-nagoya/ruri-v3-310m` の README、2026-11-17 取得）。

BM25 の `k1` 1.2 と `b` 0.75、文字バイグラムの NFKC・空白と制御文字の除去・句読点と大小の維持は、文書化した既定として閉じた。設定キーは `bm25.k1`、`bm25.b`、`keyword.char_bigram` である。k1 と b と `casefold` と `drop_punct` はベンチマークの調整候補である。

Redis のレーンは 1 で閉じた。根拠は上の Streams の節である。表の行は方針 B の1ブロック1点で閉じた。`rag_requirements.md` が方針 B を名指ししている。PipesHub の `_group_table_row_documents` は方針 C で、連続する行を1点にまとめる（`modules/transformers/vectorstore.py` L806-L812、呼び出し L3011、`acc3095`）。それを採るとチャンクの境界が要件と違う。LLM の `table_summary` で本文を上書きしない。

## 寝ている間の判断

taiga が寝ているあいだ、`rag_requirements.md` に無い細部は PipesHub（`acc3095`）に合わせ、無いものは要件の意図で決めた。

1. 決定: 融合前の候補深さは `max(limit * 2, 64)` にする。証拠: JQaRA の external id `4210070`（チャンク `db93f5c3-b144-506f-9287-ecf03b424228:0`）は Sudachi 順位 1、文字バイグラム順位 1、密順位 21 だった。`limit * 2` が 20 のとき密の枝に入らず、k=60 の RRF は `2/61` で融合順位 15 になり、ハーネスの上位 10 から外れた。密順位が 20 を超えた自己検索は 1999 件中 5 件で、最悪は 32, 32, 28, 24, 21。深さ 64 のあと、その 5 件の融合順位は 3, 1, 1, 4, 3 になった。戻し方: `branch_depth` を `return limit * 2` に戻す。
2. 決定: BM25 の候補は、上位 N を切る前に `filters.kb` のポスティングだけを残す。文書頻度は全体のまま。証拠: クエリ「スイス連邦の首都はどこ？」の全体 Sudachi 上位 64 は、jsquad-k60 が 24、jqara-k60 が 22、miracl-k60 が 18 だった。密検索はもともと kb で絞る。`filters.kb` は、他の kb が候補枠を埋めないという意味である。この絞り込みのあと MIRACL の nDCG@10 は PipesHub+ruri に届いていない。品質の穴を埋めるための変更ではなく、フィルタの正しさである。戻し方: `bm25_rows` の kb 述語を外す。

## 未決

残っていない。
