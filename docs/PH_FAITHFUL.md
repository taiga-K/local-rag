# 揃えた計測（A / B / C）

ハーネスは `bench/standalone_bench.py` の retrieve と ranx（recall@1、recall@5、recall@10、ndcg@10、mrr@10、繰り返し 5）。サブセットは `jqara-dev-s40`、`miracl-ja-dev-s30`、`jsquad-valid-s40`。接頭辞なし。タイトルなし。`maxChunksPerRecord=1` なので各脚 80。RRF は `fusion.k=1`（0 始まりの `1/(pos+2)`）。調整はしていない。

| 設定 | 脚 |
| --- | --- |
| A | 密 + fastembed `Qdrant/bm25`（0.9.1、引数なし） |
| B | 密 + Sudachi + 文字バイグラム。ほかは A と同じ |
| C | 密だけ。接頭辞なし |

PipesHub+ruri は local-rag-bench `87e97e6` の公表値。R@k は公表表に無い。

| サブセット | 系 | R@1 | R@5 | R@10 | nDCG@10 | MRR@10 | p50 ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| JQaRA | PipesHub+ruri |  |  |  | 0.9019 | 0.8986 | 150.2 |
| JQaRA | A | 0.3117 | 0.9079 | 0.9788 | 0.9055 | 0.9111 | 94.8 |
| JQaRA | B | 0.3825 | 0.8750 | 0.9425 | 0.9223 | 0.9625 | 206.5 |
| JQaRA | C | 0.3825 | 0.9142 | 0.9788 | 0.9444 | 0.9619 | 90.2 |
| MIRACL | PipesHub+ruri |  |  |  | 0.8314 | 0.8175 | 156.4 |
| MIRACL | A | 0.4267 | 0.8165 | 1.0000 | 0.8314 | 0.8175 | 94.7 |
| MIRACL | B | 0.2184 | 0.7437 | 0.9500 | 0.6977 | 0.6173 | 112.5 |
| MIRACL | C | 0.4600 | 0.8165 | 1.0000 | 0.8410 | 0.8359 | 84.1 |
| JSQuAD | PipesHub+ruri |  |  |  | 0.8928 | 0.8738 | 164.0 |
| JSQuAD | A | 0.8250 | 0.9500 | 0.9500 | 0.8928 | 0.8738 | 96.2 |
| JSQuAD | B | 0.9000 | 0.9250 | 0.9500 | 0.9247 | 0.9167 | 137.7 |
| JSQuAD | C | 0.8250 | 0.9500 | 0.9500 | 0.8895 | 0.8696 | 89.3 |

MIRACL の A は nDCG@10 0.8314、MRR@10 0.8175 で公表値と小数 4 桁まで一致する。C は再計算の「接頭辞なし密だけ」0.8410 と一致する。JSQuAD の A は nDCG@10 0.8928、MRR@10 0.8738 で公表値と一致する。JQaRA の A は nDCG@10 が公表値より 0.0036 高い。

B は MIRACL を 0.8314 から 0.6977 に下げる。JQaRA と JSQuAD では A より高い。脚は替えていない。選ぶのは計測の読み手である。

生のヒットは `bench/results/ph-faithful/<A|B|C>/<subset>/queries.jsonl` と `summary.json`。

## 採点の経路

JQaRA の A と B は `standalone_bench.py run` そのもの（自己検索の待ちを含む）。JQaRA の C は、external id `4210070` の本文先頭 80 字が密だけの上位 10 に入らず、ハーネスの待ちが終わらない。索引が COMPLETED になったあと、同じ `CompatibleClient.retrieve` と `ranx_mean` で 40 クエリを採点した（`bench/score_indexed.py`）。

MIRACL と JSQuAD も、push のあと COMPLETED を待ってから同じ採点関数を使った。MIRACL の id は `#` を含むのでハーネスは `d` + sha256 にする。採点側で元の id に戻している。戻す前の MIRACL は nDCG 0 になったので捨て、索引を作り直して採点し直した。

JQaRA の最初の索引は 2026-11-18T07:14:06Z に始まり、1999 件が COMPLETED になったのは 08:28Z 頃である。この秒数は埋め込みと fastembed と二つのトークナイザを含む。A/B の summary にある `index_seconds` は、そのあとハーネスが先頭 80 字を引き直した時間で、冷たい埋め込みではない。
