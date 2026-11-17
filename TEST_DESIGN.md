# テスト設計

この文書は `DESIGN.md` の契約を、観察できる結果へ割り当てる。テストは実装の呼び出し順や私有関数を見ない。HTTP のステータスとボディ、その後の GET、検索結果のテキストと順位、が断言の対象である。

原則は「振る舞いをテストする」である。壊れると利用者に見える結果が変わる変更で失敗し、内部だけの変更では成功したままになる断言だけを残す。

PipesHub の参照コミットは `7aff0de37be83beac220e801b83e303bd4018911` である。リンクの根は `https://github.com/pipeshub-ai/pipeshub-ai/blob/7aff0de37be83beac220e801b83e303bd4018911/` である。以下、パスだけ書く。

要件ノートのアーカイブはこの環境に無く、PipesHub テスト観点の別要約も未着である。届いたらケースを足す。待たない。

## ピラミッド

| 層 | 数の目安 | 依存 | 見るもの |
| --- | --- | --- | --- |
| 単体 | 多い | なし | チャンク境界、Sudachi とバイグラム、BM25 の得点、RRF の順位、version 判定の純粋関数 |
| 統合 | 少ない | compose の Postgres、Redis、Qdrant | push の永続化、ストリーム再配送、索引の点とポスティング |
| 端到端 | 数本 | compose 全部とモデル | サンプルファイルを CLI で入れ、日本語の問いでチャンクが返る |

単体のチャンクと RRF はモデルをロードしない。端到端だけ `ruri-v3-310m` を使う。統合の埋め込みは、決まったベクトルを返す偽の埋め込み関数に差し替える。差し替え点はプロセスの設定 `embedding.backend: fake` である。本番の既定は `sentence-transformers` である。偽はテスト用設定で、本番イメージの既定値は変えない。

## 技法

ケース群の見出しが技法名である。

- 同値分割。同じ結果になる入力を1つの類にし、類から1つ以上を取る。
- 境界値分析。範囲の両端と、1つ外を取る。
- 状態遷移。状態と事象の組を1本のテストにする。
- デシジョンテーブル。version と比較結果の組である。
- エラーの網羅。設計に書いた 4xx と 409 と 422 と 503 を、理由コードごとに1本置く。

## push の封筒

技法は同値分割と境界値分析とエラー網羅である。

モデルにした PipesHub のテストは次である。

- `backend/python/tests/unit/connectors/sources/localKB/push/test_contract.py`
- `backend/python/tests/unit/connectors/sources/localKB/push/bodies.py`
- `backend/python/tests/unit/connectors/sources/localKB/push/test_router.py`
- `backend/python/app/connectors/sources/localKB/push/admission.py` の上限

| 類または境界 | 入力の例 | 観察 |
| --- | --- | --- |
| 合法な最小 | テキスト1ブロック、version 0 | 201 `created` |
| version の下端と上端 | `0` と `2**53-1` | 201 |
| version の外 | `-1`、`2**53`、`"1"`、`1.0`、`true` | 400 `ENVELOPE_INVALID` |
| `blocksFormat` | 省略、`2`、`"1"`、`true` | 400 `ENVELOPE_INVALID` |
| `mimeType` | `text/plain` | 400 `ENVELOPE_INVALID` |
| `externalRecordId` 合法 | `a`、`x` が 256 文字、`k.v~w:x-y_z` | 201 |
| `externalRecordId` 非法 | 空、257 文字、先頭が `-`、空白、改行、`/` | 400 `ENVELOPE_INVALID`、`location` は `externalRecordId` |
| `recordName` | 空白だけ、256 文字、`<b>x</b>`、`%s` | 400 |
| `recordName` の正規化 | `"  hi  "` | 保存名は `hi` |
| 未知キー | 封筒、ブロック、`data` の余分なキー | 400 または 422。`issues` にその位置 |
| 厳密な型 | `index` が `"0"` や `true` | 422 `BLOCKS_INVALID` と `location` |
| テキスト長 | 1 MiB は合法、1 MiB+1 は 422 | 境界 |
| 空の `data` | `""` | 201。索引状態は後で `EMPTY` |
| 空の `blocks` | `{}` | 201。状態は `EMPTY` |
| ブロック数 | 設計の上限は単体で定数を見る。HTTP は 2 件と、上限を模した拒否を小さいフィクスチャで見る | 100000 件の HTTP は毎日のテストに入れない。メモリを食うからである |
| 構造 | `index` が位置と違う、親が範囲外、範囲の反転、子の重複、深さ 64 と 65 | 64 は 201、65 と他は 422 |
| 壊れた JSON | 途中で切れた本体、空、配列 | 400 `INVALID_JSON` |
| Content-Type | `application/json` と `application/blocks` は 201。`text/plain` は 415 | |
| 本体の大きさ | 16 MiB 以下の合法 JSON は通す。`Content-Length` が 16 MiB を超える宣言は 413 `PAYLOAD_TOO_LARGE` | 16 MiB の実体を毎回送らない。宣言と、読込中に上限を超える小さいストリームで見る |
| `Content-Length` | 数値でない | 400 `INVALID_CONTENT_LENGTH` |
| 知識ベース無し | 未知の `kb_id` | 404 `KB_NOT_FOUND` |
| パイプライン用フィールド | `content_hash` や `id` をブロックに付ける | 422 `BLOCKS_INVALID` |

正規化の同値類は、省略、null、空配列、既定値だけの部分オブジェクトが同じ `contentRev` になることである。キー順だけが違う JSON も同じ `contentRev` である。本文の1文字違いと `name` の追加は違う `contentRev` である。PipesHub の `test_equivalent_requests_are_byte_identical` と `test_changed_content_changes_the_digest` に対応する。黄金のダイジェスト値はコピーしない。UUID 名前空間と画像フィンガープリントの有無が違うから、同じハッシュにはならない。

## version

技法はデシジョンテーブルである。

モデルは `backend/python/tests/integration/graph_db/test_kb_push_real_backends.py` の `test_create_publishes_one_new_record`、`test_identical_push_writes_nothing`、`test_changed_content_new_document_then_update`、`test_rename_only_push_does_not_reindex` である。409 の理由文字列は `push/service.py` の `_decide` である。

| 操作 | 観察 |
| --- | --- |
| 新規 | 201 `created`、`contentChanged` true、`event` `newRecord`、GET の状態はやがて `COMPLETED` か、空なら `EMPTY` |
| 同じ version、同じ本体 | 200 `unchanged`、`contentChanged` false、`event` null。状態と `contentRev` は変わらない |
| 同じ version、違う本文 | 409 `VERSION_CONFLICT`、`currentVersion` は保存値。GET の本文は元のまま |
| より小さい version | 409 `STALE_VERSION`、`currentVersion` は保存値 |
| より大きい version、同じブロック、名前だけ違う | 200 `updated`、`contentChanged` false。チャンクのテキストは変わらない |
| より大きい version、違う本文 | 200 `updated`、`contentChanged` true、`event` `updateRecord`。検索は新しいテキストだけを返す |
| 100 回の同一 push | 保存ファイルは1つのまま。イベントは最初の1回だけ |

## 削除と再投入

技法は状態遷移である。PipesHub に同じ削除 API は無い。近いテストは `backend/python/tests/unit/connectors/sources/localKB/test_kb_delete_stored_files.py` と `tests/integration/graph_db/test_kb_delete_real_backends.py` である。ゴミ箱ではなく物理削除である点が違う。

| 遷移 | 観察 |
| --- | --- |
| 作成して削除 | 200 `deleted`。GET は 404。検索にそのテキストは出ない |
| 無い id を削除 | 404 `RECORD_NOT_FOUND` |
| 削除のあと同じ id を version 1 で再 push | 201 `created`。新しい本文が検索に出る |
| 削除を2回 | 2回目は 404 |
| `IN_PROGRESS` のあいだに削除 | 終了後の検索にそのチャンクは残らない |

## 索引の状態

技法は状態遷移である。

モデルは `ProgressStatus` と、`local_repos.py` の件数、`kb-list-view.tsx` が理由を表示することである。PipesHub に同名の reprocess ルートは見つからなかった。ケースは `DESIGN.md` の遷移表が対象である。

| 列 | 観察 |
| --- | --- |
| 本文ありの push 直後 | GET は `QUEUED` または、すでに進んでいれば `IN_PROGRESS` か `COMPLETED` |
| ワーカー成功 | `COMPLETED`、`failureReason` は null。counts の `COMPLETED` が増える |
| 空の文書 | `EMPTY`。Qdrant にその `recordId` の点は無い |
| Qdrant を止めたあとの処理 | `FAILED`、`failureReason` は `QDRANT_UNAVAILABLE` |
| `FAILED` を reprocess し、Qdrant を戻す | 202。のち `COMPLETED` |
| `COMPLETED` を reprocess | 202。のち再び `COMPLETED`。テキストは同じ |
| `IN_PROGRESS` を reprocess | 409 `IN_PROGRESS`。テストはワーカーを止めて状態を `IN_PROGRESS` にした行で行う |
| counts | 5つのキーが常にあり、合計はレコード数と一致する |

## 依存が落ちている

技法はエラー網羅である。PipesHub の対応するテストファイルは特定できない。契約は `DESIGN.md` の 503 である。

| 停止 | 操作 | 観察 |
| --- | --- | --- |
| Postgres | push | 503 `POSTGRES_UNAVAILABLE`。再起動後にその id は 404 |
| Redis | push | 503 `REDIS_UNAVAILABLE`。再起動後の同じ push は 201 になる |
| Qdrant | push | 201。のち GET は `FAILED` と `QDRANT_UNAVAILABLE` |
| Qdrant | retrieve | 503 `QDRANT_UNAVAILABLE` |
| Postgres | retrieve | 503 `POSTGRES_UNAVAILABLE` |
| Redis | retrieve | 200。検索は Redis を読まない |

統合テストは compose の依存を止めて戻す。毎日の単体には入れない。

## チャンク

技法は同値分割と境界値分析である。

モデルは `backend/python/app/modules/transformers/vectorstore.py` の `_build_text_documents`（方針 B）と `_slice_on_character_boundaries` と `_split_to_token_ceiling` である。重なりを持つ `_chunk_oversized_text` は方針 A なので、結果がそれに一致したら失敗である。

| 類 | 観察 |
| --- | --- |
| 窓より短い1ブロック | チャンクは1つ。テキストは元と一致 |
| 空と空白だけ | チャンクは0 |
| 窓ちょうどのトークン列 | 1チャンク |
| 窓+1 トークン | 2チャンク。結合すると元の文字列になる。重なりは無い |
| 画像ブロック | チャンクは0。デバッグ API のブロック一覧には残る |
| 表の行 | `cells` のテキストがチャンクに含まれる |
| ブロックが2つ | `blockIndex` は 0 と 1。長い方だけ `piece` が増える |

トークナイザはテスト用の単文字トークナイザと、モデルをロードしない固定窓で行う。端到端ではモデルの `max_seq_length` で1本だけ、長い日本語が2片以上になり、片のトークン数が窓以下であることを見る。

## トークナイザと BM25 と RRF

技法は同値分割と境界値分析である。

PipesHub に Sudachi のテストは無い。RRF の定数と式の参照は `backend/python/tests/unit/modules/retrieval/` 配下の融合テストと `result_merging.py` である。和を取る点が PipesHub の最大寄与と違うので、期待値は Cormack の式から手で計算する。実装の関数を期待値の計算に使わない。

| ケース | 観察 |
| --- | --- |
| Sudachi モード C | 「東京都」が C では分かれない、A では分かれる、ことを1例で固定する。辞書の結果が変わったら期待を更新する |
| `normalize: true` | 活用した動詞の `normalized_form` が索引語になる |
| バイグラム仮規定 | `ab c` を NFKC し空白を除くと `ab` `bc`。1文字は語が無い |
| バイグラムの境界 | 空は語が無い。1文字は0。2文字は1。3文字は2 |
| BM25 | 文書1件で、その語を含む文書の得点が、含まない文書より高い。`k1` を変えると得点は変わり、語の集合は変わらない |
| RRF k=60 | 密で順位1、キーワードで不在の得点は `1/61`。両方で順位1なら `2/61`。順位は1始まり |
| 融合の同点 | 入力順で安定する |
| トークナイザを1つにした設定 | デバッグの `breakdown` にその脚だけがあり、他は null |

## 検索 API

技法は同値分割と境界値分析とエラー網羅である。

モデルは `backend/python/tests/unit/api/routes/test_retrieve.py` と `search.py` の `RetrieveQuery` である。権限で件数が減るケースは採用しない。

| ケース | 観察 |
| --- | --- |
| 空の `query`、空白だけ | 400 |
| `limit` が 0、51 | 400 または 422。PipesHub は pydantic の範囲エラーである。ここは 422 に固定する |
| `limit` が 1 と 50 | 件数がその数以下 |
| `filters` に未知キー | 400 |
| `filters.kbId` | その知識ベースのチャンクだけ |
| 壊れた日付 | 400 |
| `rewriteQuery: true` | 400 `REWRITE_DISABLED` |
| ヒット無し | 200 `chunks: []` |
| `maxChunksPerRecord: 1` で同じ文書が上位を占める | 返るチャンクはその文書から1つまで |
| 応答のキー | `id` `text` `score` `record` `citation` が常にある |
| フィンガープリント不一致 | 409 `INDEX_CONFIG_MISMATCH`。reindex のあと 200 |

## デバッグ

技法は同値分割である。PipesHub に同じ API は無い。

| ケース | 観察 |
| --- | --- |
| push した id | 生 JSON の `externalRecordId` と、チャンクのテキストが返る |
| 未知の id | 404 |
| デバッグ検索 | 返った各チャンクについて、`dense` と各キーワードの `rank` が 1 以上であるか null である。`rrf` は返ったチャンクの間で降順である |

## 再索引

技法は状態遷移である。

| ケース | 観察 |
| --- | --- |
| 同じ設定で再起動 | 既存の点が残り、検索できる |
| 設定のモデル名だけ変えて起動 | 検索は 409。push は 201 だが新しい点は増えない |
| reindex | 202。完了後のフィンガープリントは新しい設定と一致し、古いテキストは新しい世代の検索に出る |
| `device` だけ変える | 409 にならない。フィンガープリントの外だからである |

モデルのダウンロードを2回しないため、この群は設定文字列と DB の世代行を見る統合テストを本体にする。実モデルの再索引は端到端の1本に留める。短い文書を1件入れ、フィンガープリントを手で壊し、reindex のあと検索できることだけを見る。

## CLI と端到端

技法は状態遷移と、代表同値（拡張子3種）である。

| ケース | 観察 |
| --- | --- |
| `samples` の txt、md、html を sync | counts の `COMPLETED` がファイル数と一致する |
| 日本語の問いを3つ | それぞれ、サンプルに書いた該当文が `chunks[0].text` か上位3件に含まれる |
| ファイルを編集して version が進む sync | 200 `updated`。古い文は検索に出ない |
| ファイルを消して sync | DELETE が通り、その文は検索に出ない |
| 対応しない拡張子 | push されない |
| `load` の JSONL | 行数と同じ件数の push が 201 か 200 である |

デバッグ API で、同じ問いに密とキーワードの順位が付いていることを1本見る。

## 計測

索引スループットと検索遅延はテストではなく、`scripts/measure.py` の出力である。測る前に、何を成功とみなすかをスクリプトの先頭に書く。文書数、トークン数、ウォームアップ回数、本計測回数、最小と最大と中央値を残す。モデルのロード時間は索引時間に含めない。含めないことをログで示す。数値は実行結果以外から書かない。

## テストを足すコミット

コミットメッセージに次を書く。

- どの原則か。振る舞いか、状態遷移か、境界か
- モデルにした PipesHub のテストファイルのパス。対応するファイルが無いときは「対応する PipesHub テストは無い」と書く
