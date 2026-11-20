# 検索と索引の設定一覧

この木は `cursor/bench-selfbuilt-5946`（`0dc36af`）である。タイトル前置のコミット `6aa48bc` は載っていない。あの前置は採用しない。総当たり ruri の 0.8571 は対照に使わない。コードは変えていない。

分類は次のとおり。

| 分類 | 意味 |
| --- | --- |
| 要件 | 承認済み要件か、この依頼が明示した指定。PipesHub と違っても黙って上書きしない |
| PipesHub 合わせ | PipesHub `acc3095` に合わせた。届く一覧で確認する |
| PipesHub に揃える差 | 要件が明示していない。PipesHub の計測と違う。揃える候補。コアの確認が済むまでコードは変えない |
| 文書化した既定 | 要件文には無い。こちらが既定として閉じた |
| 独自・不採用 | 要件でも PipesHub でもない。この木には入れない |

行番号は `cursor/bench-selfbuilt-5946` のファイルである。

## 明示する対照

| 項目 | こちら | 場所 | PipesHub+ruri の計測 | 分類 |
| --- | --- | --- | --- | --- |
| ruri の接頭辞 | 文書 `検索文書: `、クエリ `検索クエリ: `。コロンのあとは半角空白。v1 の `文章: ` / `クエリ: ` ではない | `kbindex/embed.py` L11-L12、L67-L72 | `encode` は `prompt_name` を渡さない、と local-rag-bench `docs/CONDITION_DIFFS.md` @ `bd22d78` が書く（`embedding_main.py` L1178-L1183）。スナップショット `18b60fb8` の `prompts` は空なので、`prompt_name` を渡してもカードの接頭辞は足されない。PipesHub コアでの再確認はまだである | PipesHub に揃える差。`DESIGN.md` L514 に写した `rag_requirements.md` はモデル名 `ruri-v3-310m` までで、接頭辞の文は無い。接頭辞はカードを見てこちらが閉じた（`DESIGN.md` L435、L520） |
| 融合前の各枝の深さ | `max(limit * 2, 64)`。limit 10 なら 64 | `kbindex/pipeline.py` L346、L483-L491 | Prefetch は `limit * 2`。limit 10 なら 20（`qdrant/utils.py` L280-L301、`acc3095`） | `limit * 2` は PipesHub 合わせ。下限 64 は独自。要件は深さを指定していない（`DESIGN.md` L530） |
| RRF の k | 既定 60。式は `1/(k+rank)`、順位は 1 始まり | `config.yaml` L18、`kbindex/config.py` L97-L99、`kbindex/rrf.py` L8-L28、`kbindex/pipeline.py` L357 | Qdrant のハイブリッドは k を渡さない。サーバ既定は 2（`qdrant/utils.py` L304-L309） | 要件。`rag_requirements.md`（`DESIGN.md` L506、L514）。黙って 2 に戻さない |
| キーワードの本数 | 3 本。密、Sudachi、文字バイグラム | `kbindex/pipeline.py` L347-L356、`config.yaml` L6 | 2 本。密と sparse の Prefetch | 密は両方にある。Sudachi は要件。文字バイグラムは次の行 |
| 文字バイグラムの枝 | Sudachi とは別に 1 本。BM25 | `kbindex/pipeline.py` L349-L356、`kbindex/tokenize.py` L37-L64、`config.yaml` L10-L15 | PipesHub の sparse は 1 本（fastembed の BM25）。文字バイグラムの枝は無い | 要件が両方を使うと言うので残す。`DESIGN.md` L514 は Sudachi を名指しし、文字バイグラムの旗は `DESIGN.md` L522 の既定。PipesHub の 1 本の sparse との差として分けて置く |
| 512 トークンでの切断 | しない。`RuriEmbedder` はモデルの `max_seq_length` をそのまま読む。このスナップショットは 8192。窓は 8190 | `kbindex/embed.py` L65、L79-L80。`kbindex` にトークン上限 512 は無い。`contract.py` L26 の 512 は表のセル数 | PipesHub の `encode` は `max_seq_length` を書き換えない（`embedding_main.py` L1178-L1183）。方針 B の窓はモデル長と `PIPESHUB_EMBED_TOKEN_LIMIT` の既定 8191 の小さい方（`vectorstore.py` L334-L347、L537-L562）。512 に切るのは総当たりの `src/jarb/ruri.py` だけ | モデルカード（8192）と一致。512 はこちらの索引ではない |
| タイトルの前置 | この木には無い | 不採用の実装は `cursor/dense-title-5946` の `6aa48bc`（`titled_blocks`）。このブランチには入れない | PipesHub+ruri は本文だけを埋める（`docs/CONDITION_DIFFS.md` @ `bd22d78`、`http_retriever.py` L34-L47）。JSQuAD の `context` は既に `タイトル [SEP]` で始まる | 独自・不採用。総当たりの数値は対照にしない |

## チャンク

| 項目 | 値 | 場所 | 分類 | 根拠 |
| --- | --- | --- | --- | --- |
| 方針 | B。1 ブロック 1 点。重なり無し。トークン境界で切る | `kbindex/chunking.py` L1、L29-L45 | 要件 | `rag_requirements.md`。`DESIGN.md` L514 |
| 窓 | `max_seq_length - 2` | `kbindex/embed.py` L79-L80、`kbindex/pipeline.py` L111 | 文書化した既定 | 方針 B の数は要件に無い |
| テキスト | ブロックの `data` | `kbindex/pipeline.py` L105-L106 | 要件 | 方針 B |
| 表の行 | セルをタブでつなぐ。行はまとめない。`table_summary` で上書きしない | `kbindex/pipeline.py` L107-L112 | 要件 | 方針 B。PipesHub の方針 C は `vectorstore.py` L806-L812、呼び出し L3011。`DESIGN.md` L524 |
| 画像 | テキストは空 | `kbindex/pipeline.py` L113-L114 | 文書化した既定 | |

## 埋め込み

| 項目 | 値 | 場所 | 分類 | 根拠 |
| --- | --- | --- | --- | --- |
| モデル | `cl-nagoya/ruri-v3-310m` | `config.yaml` L2、`kbindex/config.py` L118 | 要件 | `rag_requirements.md`。`DESIGN.md` L514 |
| 次元 | ロードしたモデルの次元。このモデルは 768 | `kbindex/embed.py` L64 | モデルカードと一致 | PipesHub も同じモデル。コードは 768 を書き込まない |
| プーリング | 上書きしない。スナップショット `1_Pooling/config.json` は mean | `kbindex/embed.py` L63-L68 | モデルカードと一致 | PipesHub の `encode` もプーリングを渡さない |
| 類似度 | Qdrant は余弦。`normalize_embeddings=True` なので内積は余弦 | `kbindex/qdrant_store.py` L46、`kbindex/embed.py` L68、L72 | モデルカードと一致 | PipesHub は `normalize_embeddings` の既定 true（`embedding_main.py` L71、L689、L1180）と余弦（`qdrant.py` L126、L558） |
| 実行 | sentence-transformers、CPU | `config.yaml` L3-L4 | 文書化した既定 | |
| モデル変更 | 点が残っているあいだは入れ直し | `kbindex/config.py` L36-L41 | 要件 | `rag_requirements.md` |

## Qdrant

| 項目 | 値 | 場所 | 分類 | 根拠 |
| --- | --- | --- | --- | --- |
| 疎ベクトル | 作らない | `kbindex/qdrant_store.py` L45-L46 | 要件 | キーワードは Postgres の BM25。`DESIGN.md` L502 |
| 距離 | 余弦 | `kbindex/qdrant_store.py` L46 | PipesHub 合わせ | `qdrant.py` L126、L558 |
| `ef_construct` | 256 | `kbindex/qdrant_store.py` L48 | PipesHub 合わせ | `qdrant.py` L95 |
| 検索 `hnsw_ef` | 256 | `kbindex/qdrant_store.py` L112 | PipesHub 合わせ | `utils.py` L42、L77-L80 |
| 量子化 | INT8、quantile 0.95、rescore、oversampling 1.5 | `kbindex/qdrant_store.py` L49-L55、L113 | PipesHub 合わせ | `qdrant.py` L159-L163、`utils.py` L43、L78-L81 |
| `m`、on_disk | `m` は未設定。ベクトルと HNSW は on_disk true | `kbindex/qdrant_store.py` L46、L48 | 文書化した既定 | PipesHub は設定を読む |
| セグメント数 | 8 | `kbindex/qdrant_store.py` L56 | PipesHub 合わせ | `qdrant.py` L582 |

## キーワード

| 項目 | 値 | 場所 | 分類 | 根拠 |
| --- | --- | --- | --- | --- |
| Sudachi BM25 | モード C、`normalized_form`。Postgres。疎ベクトルではない | `config.yaml` L8-L9、`kbindex/tokenize.py` L21-L33、`kbindex/bm25.py` L1 | 要件 | `rag_requirements.md`。`DESIGN.md` L514。PipesHub は fastembed の BM25 を Qdrant の sparse にする |
| 品詞 | 落とさない | `kbindex/tokenize.py` L30-L33 | 文書化した既定 | 内容語への絞り込みは要件が指定していない。`DESIGN.md` L514 |
| 文字バイグラムの旗 | NFKC、大小は維持、空白と制御は落とす、句読点は残す | `config.yaml` L10-L15、`kbindex/tokenize.py` L37-L64 | 文書化した既定 | `DESIGN.md` L522 |
| BM25 の k1、b | 1.2、0.75。IDF は全 kb | `config.yaml` L19-L21、`kbindex/bm25.py` L12-L13、L64 | 文書化した既定 | `DESIGN.md` L522 |
| kb で切る | 候補のポスティングだけ `filters.kb`。df は全体 | `kbindex/db.py` L355、L366-L376、`kbindex/pipeline.py` L351 | PipesHub 合わせ | scope があるとき Prefetch はフィルタのあとで切る（`utils.py` L276-L278） |

## 融合の後段

| 項目 | 値 | 場所 | 分類 | 根拠 |
| --- | --- | --- | --- | --- |
| 方式 | RRF だけ | `config.yaml` L16-L17、`kbindex/config.py` L79-L81 | 要件 | `rag_requirements.md`。`fusion_methods.md` |
| レコードへの集約 | `maxChunksPerRecord` があれば融合順の先着 | `kbindex/pipeline.py` L359-L368 | 文書化した既定 | ハーネスは 1 を送る |
| retrieve の件数 | 既定 10、上限 10 | `kbindex/api.py` L174-L176 | 要件 | この依頼の「既定 10、上限 10」。PipesHub は既定 8、上限 50。`DESIGN.md` L516 |
| スコア閾値 | 既定オフ。オンのとき、融合後かつ `limit` の前に、余弦が閾値未満の候補とベクトルの無い候補を落とす。オフのときは落とさず `similarity` を付ける。`score` は RRF のまま。閾値の既定 0.5 は `DEFAULT_SCORE_THRESHOLD` だけ | `kbindex/similarity.py`、`kbindex/pipeline.py` の `search`、`GET/PUT /api/v1/settings/retrieve` | この依頼 | Dify の `score_threshold_enabled` と `score_threshold`。リランカは足さない |
| リランカ | 無い | `DESIGN.md` L498 | 要件 | `rag_requirements.md` |
| クエリ書き換え | `rewriteQuery: true` は 400 | `kbindex/api.py` L169-L173 | 要件 | LLM が無い |

## 要件による差分

黙って PipesHub に戻さない。

| 項目 | こちらの値 | 出典 | PipesHub |
| --- | --- | --- | --- |
| チャンク方針 B | 1 ブロック 1 点、重なり無し、表の行はまとめない | `rag_requirements.md` | 表は方針 C |
| RRF の k | 60 | `rag_requirements.md` | サーバ既定 2 |
| Sudachi BM25 | モード C、正規化形、Postgres | `rag_requirements.md` | fastembed BM25 の sparse |
| モデル | ruri-v3-310m | `rag_requirements.md` | 既定は bge。接頭辞はこの行に含めない |
| リランカ | 無い | `rag_requirements.md` | ある |
| retrieve の件数 | 既定 10、上限 10 | この依頼 | 既定 8、上限 50 |
| 方式の変更 | 全件入れ直し | `rag_requirements.md` | 点が残っているあいだモデルは替えない |

融合の k や枝の深さを探す計測は始めていない。
