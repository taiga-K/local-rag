# 自前索引のベンチマーク

ハーネスは `bench/standalone_bench.py` である。local-rag-bench `f4f8233` のファイルをそのまま置いてある。ハッシュ行は変えていない。`python bench/standalone_bench.py verify` は 9 本とも一致した。

比較先は local-rag-bench `87e97e6`（PipesHub `acc3095`、limit 10）の公表値である。PipesHub の R@1/5/10、p95、索引秒はこの表に無い。ここには書かない。

## 測った条件

- モデルは `cl-nagoya/ruri-v3-310m`。文書の接頭辞は `検索文書: `、クエリは `検索クエリ: `。
- 融合は RRF だけ。既定の `fusion.k` は 60。k=2 は設定を変えて API とワーカーを起動し直した。再索引はしていない。k はフィンガープリントに入らない。
- 候補深さは `max(limit * 2, 64)`。BM25 は `filters.kb` のポスティングだけを、上位を切る前に残す。文書頻度は全体のまま。`bm25.k1` は 1.2、`b` は 0.75。
- サブセットは `jqara-dev-s40`（1999 文書、40 クエリ）、`miracl-ja-dev-s30`（292、30）、`jsquad-valid-s40`（1145、40）。KB は `jqara-k60`、`miracl-k60`、`jsquad-k60`。サニティは `keep` が 1 位で通った。エラーは 0。順位は 5 回の繰り返しで安定。
- 品質の数字は、kb 絞り込みと深さ 64 を入れたあとのハーネスである。ログは `bench/results/k60-fixed.log`（ALL_DONE `2026-11-18T01:31:50Z`）と `bench/results/k2-fixed.log`（ALL_DONE `2026-11-18T02:12:04Z`）。

この VM で測ったもの: 4 vCPU（Intel Xeon）、`MemTotal` 16387328 kB。計測後の `docker stats` は api 935 MiB、worker 659 MiB、qdrant 46 MiB、postgres 257 MiB、redis 8 MiB。`dmesg` に `virtio_balloon ... Out of puff` と、VM fork による `crng reseeded` がある。PipesHub の数字は別の記録で、この VM では測っていない。ハードウェア差は推定である。

## ハーネスの結果

`index_seconds` はハーネスの `push_seconds + wait_seconds` である。wait は各文書の本文先頭 80 字を limit 10 で引き、その id が上位 10 に入るまで待つ。埋め込みだけの時間ではない。k=60 の再計測と k=2 は、最初の k=60 で作ったコレクションを再利用している。k=2 の索引秒は冷たい埋め込みではない。

| サブセット | 系 | R@1 | R@5 | R@10 | nDCG@10 | MRR@10 | index_seconds | p50 ms | p95 ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| JQaRA | PipesHub 既定 |  |  |  | 0.3635 | 0.4705 |  | 212.9 |  |
| JQaRA | PipesHub+ruri |  |  |  | 0.9019 | 0.8986 |  | 150.2 |  |
| JQaRA | 自前 k=60 | 0.3825 | 0.8296 | 0.9242 | 0.8965 | 0.9661 | 510.7 | 183.1 | 228.2 |
| JQaRA | 自前 k=2 | 0.3575 | 0.8604 | 0.9675 | 0.9134 | 0.9525 | 523.1 | 183.8 | 242.8 |
| MIRACL | PipesHub 既定 |  |  |  | 0.4191 | 0.4326 |  | 186.2 |  |
| MIRACL | PipesHub+ruri |  |  |  | 0.8314 | 0.8175 |  | 156.4 |  |
| MIRACL | 自前 k=60 | 0.3128 | 0.7410 | 0.8917 | 0.7116 | 0.6839 | 60.3 | 128.4 | 137.5 |
| MIRACL | 自前 k=2 | 0.3017 | 0.7587 | 0.9417 | 0.7283 | 0.6762 | 60.4 | 130.6 | 145.0 |
| JSQuAD | PipesHub 既定 |  |  |  | 0.6058 | 0.5517 |  | 187.5 |  |
| JSQuAD | PipesHub+ruri |  |  |  | 0.8928 | 0.8738 |  | 164.0 |  |
| JSQuAD | 自前 k=60 | 0.9000 | 0.9500 | 0.9750 | 0.9343 | 0.9217 | 289.9 | 143.8 | 179.2 |
| JSQuAD | 自前 k=2 | 0.9000 | 0.9750 | 1.0000 | 0.9441 | 0.9269 | 290.9 | 149.5 | 183.7 |

PipesHub+ruri との差（自前 − 公表）:

| サブセット | k | nDCG@10 | MRR@10 | p50 ms |
| --- | ---: | ---: | ---: | ---: |
| JQaRA | 60 | −0.0054 | +0.0675 | +32.9 |
| JQaRA | 2 | +0.0115 | +0.0539 | +33.6 |
| MIRACL | 60 | −0.1198 | −0.1336 | −28.0 |
| MIRACL | 2 | −0.1031 | −0.1413 | −25.8 |
| JSQuAD | 60 | +0.0415 | +0.0479 | −20.2 |
| JSQuAD | 2 | +0.0513 | +0.0531 | −14.5 |

JSQuAD は nDCG@10 と MRR@10 で PipesHub+ruri を上回る。JQaRA は k=60 の nDCG@10 だけ 0.0054 下回り、MRR@10 は上回る。k=2 の JQaRA nDCG@10 は上回る。MIRACL は nDCG@10 も MRR@10 も下回る。R@10 は 0.8917（k=60）と 0.9417（k=2）なので、関連文書は上位 10 には入ることが多く、1 位に来ていない。

最初の k=60（深さ 64、kb 絞り込みの前）の冷たい実行は `bench/results/k60-run.log` にある。JQaRA の `index_seconds` 479.77（push 58.38、wait 421.38、nDCG@10 0.8979、MRR@10 0.9675）は `bench/results/cold-k60/jqara-dev-s40/summary.json` に残している。MIRACL のプロセスは `2026-11-17T22:58:06Z` から `23:18:08Z`（壁時計 1202 秒）、JSQuAD は `23:18:08Z` から `2026-11-18T00:28:04Z`（壁時計 4196 秒）。この 2 本の summary は再計測で上書きされ、`index_seconds` フィールドは残っていない。壁時計はクエリの 5 回繰り返しを含む。上の表の 60.3 秒と 289.9 秒は、その冷たい埋め込みではない。

## アブレーション

JQaRA の k=60 nDCG@10 と、MIRACL の nDCG@10 と MRR@10 が PipesHub+ruri を下回ったので、同じ 110 クエリを枝ごとに測った。スコアは `bench/results/ablation/scores.json`。ヒットは `ablate-hits.json`（770 行）。キーワードだけの 2 行はヒットファイルには無く、ホストから `bm25_rows` を kb 付きで引いて ranx した。

`Engine.search` は常に密の枝を足す。ヒットファイルの `sudachi` と `bigram` は密＋そのキーワードであり、`dense-sudachi-k60` と `dense-bigram-k60` と同じである。キーワードだけは密を呼んでいない。

nDCG@10:

| 枝 | JQaRA | MIRACL | JSQuAD |
| --- | ---: | ---: | ---: |
| 密だけ | 0.9501 | 0.8195 | 0.9173 |
| Sudachi だけ | 0.7843 | 0.6835 | 0.9247 |
| 文字バイグラムだけ | 0.8124 | 0.6388 | 0.9512 |
| 密＋Sudachi、k=60 | 0.9165 | 0.7519 | 0.9312 |
| 密＋バイグラム、k=60 | 0.9323 | 0.7457 | 0.9270 |
| 3 本、k=60 | 0.8965 | 0.7153 | 0.9343 |
| 3 本、k=2 | 0.9136 | 0.7320 | 0.9441 |

3 本の k=60 はハーネスと 0.004 以内で合う（MIRACL はプロセス内 0.7153、HTTP 0.7116）。MIRACL は密だけが 0.8195 で、PipesHub+ruri の 0.8314 まで 0.0119 である。キーワードを足すと下がる。k=2 の 3 本でも 0.7283 で、0.8314 には届かない。JQaRA は密だけも密＋1 本も PipesHub+ruri の 0.9019 を上回り、3 本の k=60 だけが 0.0054 下回る。

要件は RRF、k の既定 60、Sudachi と文字バイグラムの両方である。足を外すことと、既定の k を 2 にすることはしない。kb 絞り込みは `filters.kb` の正しさであり、MIRACL の差は残っている。これ以上の変更はしていない。

## 再現

```
python bench/standalone_bench.py verify
python bench/standalone_bench.py run --subset jqara-dev-s40 \
  --base-url http://127.0.0.1:43123 --kb jqara-k60 --sanity-kb jqara-k60-sanity \
  --out bench/results/selfbuilt-k60/jqara-dev-s40
```

MIRACL と JSQuAD も同じ形である。k=2 は `config.yaml` の `fusion.k` を 2 にして API とワーカーを起動し直し、同じ KB に対して `--out bench/results/selfbuilt-k2/<subset>` を走らせる。リポジトリの `fusion.k` は 60 のままである。
