# PipesHub との対照（426fc25、訂正後）

PipesHub は main `426fc25a96e67ec73297c823df851093794471ee`。行はそこのもの。こちらは `cursor/align-pipeshub-5946`。分類は二つだけ。

| 分類 | 意味 |
| --- | --- |
| PipesHubに揃える | この依頼が揃えると言ったもの。要件の文が無い |
| 要件による差分 | `rag_requirements.md` が名指しするもの。この木にそのファイルは無い。引用は `DESIGN.md` の写しと、この依頼の文言 |

ベンチの経路は `application/blocks` の push と `POST /api/v1/retrieve` で、`maxChunksPerRecord=1`、`limit=10`、`rewriteQuery=false`。見出しの結合はしない。本文は 1 ブロックなので 1 文書 1 点。

| 項目 | こちら | 場所 | PipesHub | 分類 |
| --- | --- | --- | --- | --- |
| ruri の接頭辞 | 付けない。クエリと文書は同じ文字列 | `kbindex/embed.py` L64-L70 | `encode` は `prompt_name` も `prompt` も渡さない。クエリと文書は同じ `encode`（`embedding_main.py` L1176-L1184） | PipesHubに揃える |
| タイトル | 付けない。この木に `titled_blocks` は無い。ハーネスは `text` だけを送る（`bench/standalone_bench.py` L421-L428） | ハーネス L421-L428 | 普通のテキストブロックにタイトルを付けない（`vectorstore.py` L871-L937）。見出し結合は Markdown の見出し直後だけ（`markdown_to_blocks.py` L663-L692）。blocks の push には当たらない | PipesHubに揃える |
| 融合前の深さ | `maxChunksPerRecord` があるとき `min(limit*4, 200)*2`。limit 10 かつ 1 なら 80。無いときは `limit*2` | `kbindex/pipeline.py` L530-L538 | retrieve は内部件数 `min(limit*4, 200)`（`search.py` L128-L141、L798）。各 Prefetch はその 2 倍（`qdrant/utils.py` L265-L313）。limit 10 かつ `maxChunksPerRecord=1` なら 80。20 ではない | PipesHubに揃える |
| RRF | 1 始まりの `1/(k+rank)`。`fusion.k` は 1。これは 0 始まりの `1/(pos+2)`。`k=2` ではない | `config.yaml` の `fusion.k`、`kbindex/rrf.py` L23-L28、`kbindex/config.py` の既定 | `Fusion.RRF` で k を渡さない（`qdrant/utils.py` L304-L309）。Qdrant v1.15 は `1/(position+2)`、position は 0 始まり | PipesHubに揃える。衝突: `DESIGN.md` のノートは「承認済み要件が k=60 を指定している」と書く。`rag_requirements.md` はこの木に無い。この依頼は A も B も `1/(pos+2)` と指定した |
| 脚（A） | 密 1 本と fastembed `Qdrant/bm25` 1 本。引数なし。版 0.9.1 | `kbindex/fastembed_bm25.py`、`config.yaml` の `search.legs` | 密 1 本と sparse 1 本（`sparse_embeddings.py` L31、L69-L90、`pyproject.toml` の `fastembed==0.9.1`） | PipesHubに揃える |
| 脚（B） | A の sparse を Sudachi BM25 と文字バイグラム BM25 に替える。深さ 80、接頭辞なし、k=1 はそのまま | `kbindex/pipeline.py` の `search`、`kbindex/tokenize.py` L21-L33 と L37-L64 | sparse は 1 本の fastembed だけ。文字バイグラムは無い | 要件による差分。この依頼が「Sudachi BM25 と文字バイグラムの脚」と名指しした。Sudachi の写しは `DESIGN.md` L514「Sudachi モード C と `normalize: true`」 |
| 文字バイグラム | Sudachi とは別の 1 本。NFKC、大小は維持、空白と制御は落とす、句読点は残す | `kbindex/tokenize.py` L37-L64、`config.yaml` の `char_bigram` | 無い | 要件による差分。この依頼が独立した行として残すと言った。旗の写しは `DESIGN.md` L522（文書化した既定）。脚そのものはこの依頼が要件とした |
| fastembed の得点 | 文書重み × `log((N-n+0.5)/(n+0.5)+1)`。Okapi ではない | `kbindex/pipeline.py` L471-L486 | fastembed が TF 重みを出し、IDF は Qdrant の `Modifier.IDF`（`qdrant.py` L277-L278、L572-L577）。再計算が 0.8314 に一致した式は上の対数 | PipesHubに揃える |
| 512 での切断 | しない。モデルの `max_seq_length`（このスナップショットは 8192）を読む。窓は 8190 | `kbindex/embed.py` L62、L76-L77。`contract.py` の 512 は表のセル数 | `max_seq_length` を代入しない（`embedding_main.py` L835-L836）。ruri-v3 は 8192。8191 トークンか 5 万文字を超えたときだけ 1500 文字・重なり 200 で割る（`vectorstore.py` L241-L243、L706-L744） | PipesHubに揃える。MIRACL の段落はこの窓に入る。512 は総当たりの `src/jarb/ruri.py` だけで、こちらの索引ではない |
| チャンク | 方針 B。1 ブロック 1 点。重なり無し。ハーネスは 1 文書 1 ブロック | `kbindex/chunking.py` L1 | 既定は方針 A。日本語の段落は 100 語を超えないので、結果は 1 段落 1 点（`vectorstore.py` L251-L260、L922） | 要件による差分。写し: `DESIGN.md` L514「チャンク方針 B」。このベンチでは両方とも 1 文書 1 点 |
| モデル | `cl-nagoya/ruri-v3-310m` | `config.yaml` | 既定は `BAAI/bge-large-en-v1.5`（`ai_models.py` L4）。ruri は設定で名指しする | 要件による差分。写し: `DESIGN.md` L514「ruri-v3-310m」 |
| 次元、プーリング、正規化、余弦 | 768、mean はモデルのまま、`normalize_embeddings=True`、Qdrant は余弦 | `kbindex/embed.py` L61-L69、`kbindex/qdrant_store.py` L46 | 次元は 1 文の長さ。正規化の既定は true（`embedding_main.py` L71-L75）。距離は余弦（`qdrant.py` L125-L129、L558） | PipesHubに揃える |
| HNSW と INT8 | `ef_construct` 256、検索 `hnsw_ef` 256、INT8 quantile 0.95、rescore、oversampling 1.5 | `kbindex/qdrant_store.py` L48-L55、L112-L113 | 同じ（`qdrant.py` L140-L165、L584-L595、`utils.py` L40-L45、L69-L82） | PipesHubに揃える |
| リランカ | 無い | `DESIGN.md` のノート | retrieve / search に cross-encoder は無い（`retrieval_service.py` L2722 はコメント） | 要件による差分。写し: `DESIGN.md` L514「リランカ無し」 |
| クエリ書き換え | `rewriteQuery: true` は 400。ハーネスは false | `kbindex/api.py` L184-L188 | `/retrieve` の既定は false（`search.py` L155-L157）。`/search` の既定は true | 要件による差分。写し: `DESIGN.md`「`rewriteQuery: true` は 400 である。LLM が無い」。ベンチは retrieve なので PipesHub の計測経路とも false |
| 1 レコードの件数 | ハーネスが `maxChunksPerRecord: 1` を送る。最終は 1 文書 1 件、上位 10 | `bench/standalone_bench.py` L444-L448 | 同じ経路では候補を読み切ってから 1 件に切り、ページは `limit`（`search.py` L819-L848）。`/search` の `max(4, limit//6)` はこの経路では使わない | PipesHubに揃える |
| 候補の kb | 上位の前に `filters.kb`。df は集合全体 | `kbindex/db.py` `bm25_rows` | Prefetch に scope フィルタ（`utils.py` L265-L278）。IDF はコレクション単位 | PipesHubに揃える |
| retrieve の既定と上限 | 既定 10、上限 10 | `kbindex/api.py` L189-L191 | `/retrieve` は既定 8、上限 50（`search.py` L128-L129、L148） | 要件による差分。写し: `DESIGN.md` L516「この依頼が『既定 10、上限 10』と指定した」 |

総当たり ruri の 0.8571 は対照に使わない。タイトルと接頭辞が入っている。
