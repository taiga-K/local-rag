# 取り込み管理アプリUIの根拠調査（2026-11-20）

grok-4.6（xhigh、ライブ検索）による2本の調査を統合。Part A は調査1（利用者のタスクと不満）、Part B は調査2〜5。

Researchy の再確認（curl、2026-11-20）: Dify #29901（2025-12-18作成、タイトル一致）、RAGFlow #9466、Microsoft Copilot Connectors October 2026 記事、JCarterJohnson/vibecoded-design-tells、NN/g Vanity Metrics、Fluent 2 Layout、Dropbox check-sync-status はいずれも200。VS Code explorerViewer.ts の ITEM_HEIGHT = 22 は現行 main では L77（報告本文の L75–81 の範囲内）。

---

# Part A: 調査1
調査日 **2026-11-20**。件数は GitHub Search API（未認証、open+closed 合算）の `total_count` を、クエリと対象リポジトリつきで書いた。HTML 検索ページは JS 描画のため件数を取れなかった。リアクション数は API 結果に含まれず、**未確認**。コメント数は API が返した値のみ。キーワード検索なので無関係ヒットを含む。

---

## 調査方法

| 項目 | 内容 |
|---|---|
| 調査日 | 2026-11-20 |
| GitHub 件数 | `https://api.github.com/search/issues?q=...` の `total_count`。`is:issue` のみ（Discussion は別）。open+closed |
| スター | 同日 `GET /repos/{owner}/{repo}` の `stargazers_count`。PipesHub は org ページの表示値 |
| 公式 | Dify / Open WebUI / AnythingLLM / RAGFlow / Onyx / PipesHub / Glean / Microsoft Learn / Tech Community |
| 利用者の声 | GitHub Issues・Discussions、Reddit、Microsoft Community Hub |
| UX 研究 | NN/g ヒューリスティック #1（状態の可視化）、#9（エラーからの回復）、進捗インジケータ |

PipesHub のリポジトリは `pipeshub-ai/pipeshub` ではなく **`pipeshub-ai/pipeshub-ai`**。旧 Danswer リポジトリ `danswer-ai/danswer` は API が 422（検索不可）だった。

---

## 各 OSS の GitHub スター（2026-11-20）

| 製品 | リポジトリ | スター | 出典 |
|---|---|---:|---|
| Dify | [langgenius/dify](https://github.com/langgenius/dify) | 161,564 | GitHub API |
| Open WebUI | [open-webui/open-webui](https://github.com/open-webui/open-webui) | 159,143 | GitHub API |
| RAGFlow | [infiniflow/ragflow](https://github.com/infiniflow/ragflow) | 94,475 | GitHub API |
| AnythingLLM | [Mintplex-Labs/anything-llm](https://github.com/Mintplex-Labs/anything-llm) | 68,460 | GitHub API |
| Onyx（旧 Danswer） | [onyx-dot-app/onyx](https://github.com/onyx-dot-app/onyx) | 33,485 | GitHub API |
| PipesHub | [pipeshub-ai/pipeshub-ai](https://github.com/pipeshub-ai/pipeshub-ai) | 4,137 | [org ページ](https://github.com/pipeshub-ai)（2026-11-19 表示） |
| Glean | 商用。公開リポジトリなし | — | — |
| Microsoft 365 Copilot コネクタ | 商用（admin center） | — | — |

---

## 管理者が取り込み画面を開くとき（公式の記述）

公式ドキュメントが想定する操作タイミングは、製品を横断して次の5つに揃う。

### 1. 初期設定（コネクタ接続・フォルダ／ファイル指定・初回同期）

- **Dify**: Knowledge を作成し、ローカルファイルまたはオンラインソースを取り込み、チャンク／索引方法を設定したあと「埋め込み完了を待つ」。完了後にアプリへ接続する。[Create Knowledge Base](https://docs.dify.ai/en/guides/knowledge-base/create-knowledge-and-upload-documents)。Agent KB では Document ページが **Ready** になるまで待ってから、索引済み文書の確認・検索テストへ進む。[Create an Agent Knowledge Base](https://docs.dify.ai/en/cloud/use-dify/knowledge-base/create-knowledge-base)
- **Open WebUI**: Workspace > Knowledge で作成し、ファイルを上げ、**処理完了を待ってから**質問する。[Knowledge](https://docs.openwebui.com/features/workspace/knowledge.md)
- **AnythingLLM**: ワークスペースへ文書を embed する。v1.12.1 以降は文書ごとの埋め込み進捗を出す。[changelog v1.12.1](https://docs.anythingllm.com/changelog/v1.12.1)
- **RAGFlow**: データセットへ文書を上げ、解析を走らせ、文書一覧で進捗を見る。[Files: Dataset Document Management](https://ragflow.io/docs/files_dataset_document_management)
- **Onyx**: Admin Panel → Connectors で認証・範囲・スケジュールを設定し、Create で索引開始。初回は **Indexing Status** で追う。[Connectors overview](https://docs.onyx.app/admins/connectors/overview)
- **PipesHub**: オンボーディング Step 5 でコネクタ認証。[Onboarding](https://docs.pipeshub.com/onboarding)。コネクタは「一方通行の同期」「定期同期（リアルタイムではない）」。[Connectors overview](https://docs.pipeshub.com/connectors/overview)
- **Glean**: 初回同期は **Crawling（1/2）→ Indexing（2/2）**。Admin Console > Data sources で Items synced が増えるかを見る。[Connect Data Sources](https://docs.glean.com/get-started/setup/connect-data-sources)
- **Microsoft 365 Copilot コネクタ**: 接続作成後、Your Connections で **Syncing → Ready**。大量サイトでは Ready まで待ってから検証する。[SharePoint Server connector deployment](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/sharepoint-server-deployment)

### 2. 日常監視（初回クロール中と、定常の鮮度）

- **Glean**: 初回は Crawl Rate、完了後は Change Rate。Items synced が 24 時間止まれば停滞として扱う。Status の Active は「有効」であり、直近クロール成功ではない。[Monitor connector health](https://docs.glean.com/connectors/connectors-health-index)、[Manage connectors](https://help.glean.com/connectors/monitoring)
- **Microsoft**: Connection state（Syncing / Ready / Paused / Failed）。Last sync time が鮮度。[Manage connectors](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/manage-connector)。2026-10 更新で、以降の full crawl でも items/groups のライブ進捗を出す（「長いクロールが止まって見える」ことを防ぐため）。[Copilot Connectors Update: October 2026](https://techcommunity.microsoft.com/blog/microsoft-copilot-blog/microsoft-copilot-connectors-update-october-2026/4572240)
- **Onyx**: 既存コネクタの状態・文書数・最終索引は **Admin Panel → Indexing Status**。[Connectors overview](https://docs.onyx.app/admins/connectors/overview)。Operator ロールは「schedule and monitor indexing」。
- **RAGFlow**: 文書一覧の waiting / running / completed / failed / canceled。長時間未完了は Logs。[Files](https://ragflow.io/docs/files_dataset_document_management)、[Logs](https://ragflow.io/docs/dataset_logs)

### 3. 失敗対応

- **Dify**: 文書は `waiting → parsing → cleaning → splitting → indexing → completed | error`。失敗時は Retry。クォータ超過の文書は Error のままリストに残り、容量を空けてから Retry。[Knowledge Storage](https://docs.dify.ai/en/cloud/use-dify/knowledge/knowledge-storage-limit)。Agent KB はステータスにホバーして理由を見て Retry。[Maintain an Agent Knowledge Base](https://docs.dify.ai/en/cloud/use-dify/knowledge-base/maintain-knowledge-base)
- **RAGFlow**: 失敗は Logs を見て原因確認し、再解析。[Files](https://ragflow.io/docs/files_dataset_document_management)
- **Onyx**: Failed は一時的なら数時間で再試行。文書単位の失敗はコネクタページに列挙し、**失敗文書だけ Retry**。続くなら Full Re-index。[Connectors overview](https://docs.onyx.app/admins/connectors/overview)
- **Glean**: 資格情報切れ・失敗アラートは無効化不可。遅延対応は鮮度低下と権限ギャップのリスク。[Monitor connector health](https://docs.glean.com/connectors/connectors-health-index)
- **Microsoft**: Failed は手動介入。Error タブにコード・件数・ログダウンロード。恒久失敗はサービス正常性へ通知。メール購読可。[Manage connectors](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/manage-connector)、[Monitor connector errors](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/error-responses)

### 4. 文書の追加・削除・「入っているか」確認

- **Dify**: Documents で Add File。無効化／アーカイブ／削除。[Maintain documents（legacy）](https://legacy-docs.dify.ai/guides/knowledge-base/knowledge-and-documents-maintenance/maintain-knowledge-documents.md)。同名アップロードは置換ではなく二重になる。[Maintain Agent KB](https://docs.dify.ai/en/cloud/use-dify/knowledge-base/maintain-knowledge-base)
- **Open WebUI**: 処理完了前に KB へ追加すると 400。ステータス API で `completed` / `failed` を待つ。[API Endpoints](https://docs.openwebui.com/reference/api-endpoints)
- **RAGFlow**: 解析後に文書名をクリックしてチャンクを確認。[Chunk management](https://ragflow.io/docs/chunk_parsing_results_and_knowledge_fragment_management)
- **Glean**: 特定 URL について crawled / indexed / 権限 / 設定除外を **Access Verification** で切り分ける。[Monitor connector health](https://docs.glean.com/connectors/connectors-health-index)
- **Microsoft**: **Index browser** に URL を入れて、そのアイテムが索引にあるかを確認。[SharePoint Server deployment](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/sharepoint-server-deployment)、[Search and validate indexed content](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/indexed-content)

### 5. 再索引・設定変更・削除の反映

- **Dify**: 埋め込みモデル変更は全文書の再索引（トークン消費）。小さいうちに決める。[Create Agent KB](https://docs.dify.ai/en/cloud/use-dify/knowledge-base/create-knowledge-base)
- **Open WebUI**: Admin Settings > Documents > Reindex Knowledge Base Vectors。既存コレクションを消し、現行エンジンで再抽出。[RAG](https://docs.openwebui.com/features/chat-conversations/rag/)
- **Onyx**: Update Index（差分）と Full Re-index（全件、大型ソースで数時間〜数日）。権限変更も再索引。[Connectors overview](https://docs.onyx.app/admins/connectors/overview)、[Index Settings](https://docs.onyx.app/admins/advanced_configs/search_configs)
- **PipesHub**: `POST /api/v1/connectors/:connectorId/reindex`。[Connector manager](https://docs.pipeshub.com/system-overview/connector-manager)
- **Glean**: 削除は数分〜数時間、イベントを逃すと次回 full crawl（コネクタにより 6 時間〜28 日）。[Crawling FAQ](https://docs.glean.com/connectors/crawling-faq)
- **Microsoft**: オンデマンドで full / incremental。削除検出が不安定だと 28 日未再発見で索引から落とす。[Manage connectors](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/manage-connector)

---

## テーマ別：利用者の不満と要望（GitHub 件数の多い順）

順位は、**比較的狭いクエリ**の Search API 件数と、公式が「そのために画面を開け」と書いている強さの合成。広いクエリ（例: Dify `indexing error` = 667、`delete ... vector` = 10,612）は順位に使わない。

### 1. 取り込みが終わったか分からない／進捗が止まる（stuck）

GitHub Search API（2026-11-20、open+closed）:

| クエリ | total_count |
|---|---:|
| `repo:langgenius/dify is:issue stuck indexing` | **115** |
| `repo:langgenius/dify is:issue "Queuing"` | **101** |
| `repo:infiniflow/ragflow is:issue parsing stuck` | **135** |
| `repo:infiniflow/ragflow is:issue "stuck" (parse OR parsing OR knowledge)` | **231** |
| `repo:open-webui/open-webui is:issue knowledge stuck` | **46** |
| `repo:onyx-dot-app/onyx is:issue indexing stuck` | **18** |
| `repo:onyx-dot-app/onyx is:issue "indexing stuck" OR "stuck at Indexing"` | **7** |
| `repo:pipeshub-ai/pipeshub-ai is:issue indexing` | **63** |
| `repo:Mintplex-Labs/anything-llm is:issue embedding stuck OR "not moving"` | **503**（広い。下の個別 Issue を優先） |

公式が「止まったら調べろ」と書く例:

- Glean: Sync が Indexing のまま進まない、Items synced が 24h 以上伸びない。[When to investigate](https://docs.glean.com/connectors/connectors-health-index)
- Microsoft: Syncing 中はオンデマンドクロール不可。長いクロールが止まって見える問題に対し、2026-10 に full crawl のライブ進捗を追加。[October 2026 update](https://techcommunity.microsoft.com/blog/microsoft-copilot-blog/microsoft-copilot-connectors-update-october-2026/4572240)
- NN/g: 10 秒超の待ちはパーセントまたはステップ一覧が要る。ループアニメだけでは「待つか他の作業に移るか」を決められない。[Progress Indicators](https://www.nngroup.com/articles/progress-indicators/)、[Designing for Long Waits](https://www.nngroup.com/articles/designing-for-waits-and-interruptions/)、[Heuristics for complex apps](https://www.nngroup.com/articles/usability-heuristics-complex-applications/)

実例:

| 製品 | Issue | 日付 | コメント | 内容 |
|---|---|---|---:|---|
| Dify | [#29901 New documents stuck in Indexing and Queing](https://github.com/langgenius/dify/issues/29901) | 2025-12-18 | API 未取得 | Cloud v1.11.1。30 分超 Queuing/Indexing。メンテ回答: **stuck かつ error でない場合、UI に force re-index はなく、pause/resume/sync のみ** |
| Dify | [#28994 New files … stuck in Queuing or Indexing](https://github.com/langgenius/dify/issues/28994) | 2025-12-01 | — | Cloud。waiting→parsing→splitting→indexing。エラー未処理だと無限待ち |
| Dify | [#30154 Files Stuck in Queuing/Indexing](https://github.com/langgenius/dify/issues/30154) | 2025-12-25 | — | **ダッシュボードにエラーが出ない**。再アップロード・再起動でも解消せず |
| Dify | [#28513 Document indexing task stuck in Queuing](https://github.com/langgenius/dify/issues/28513) | 2025-11-21 | — | Worker が `priority_dataset` を購読しておらず Queuing のまま。SQL で error にしてから UI の Reindex で成功 |
| Dify | [#29007 Dataset stuck in "Queuing"](https://github.com/langgenius/dify/issues/29007) | 2025-12-02 | — | 小さな .txt でも無限 Queuing |
| Dify | Reddit [stuck on Knowledge](https://www.reddit.com/r/difyai/comments/1kjzrox/newbie_having_play_with_dify_stuck_on_knowledge/) | 2025-05-11 | スコア1 | 数時間 Queuing。24h 後に error。アカウント削除 |
| RAGFlow | [#9070 I tried three version … stuck on Knowledge base](https://github.com/infiniflow/ragflow/issues/9070) | 2025-07-28 | — | 原因は task executor 未起動。UI の System で心拍を見る運用 |
| RAGFlow | [#9466 parse stop after less than 1%](https://github.com/infiniflow/ragflow/issues/9466) | 2025-08-14 | — | 1% 未満で停止。**再起動以外にデッドロック解除がない** |
| RAGFlow | [#8495 How can we recover when parsing gets stuck?](https://github.com/infiniflow/ragflow/issues/8495) | 2025-06-25 | — | UI の stop だけでは足りず、MySQL/Redis の手作業が必要、という質問 |
| RAGFlow | [#7449 Parsing stuck … resource usage drops to 0](https://github.com/infiniflow/ragflow/issues/7449) | 2025-04-30 | — | 解析開始後に CPU/GPU が 0 になりアイドル |
| RAGFlow | [#13171 Documents stuck in "Parsing" after reboot](https://github.com/infiniflow/ragflow/issues/13171) | 2026-02-20 | — | Redis 再起動後、未完了タスクが自動再キューされない |
| Onyx | [#11379 Indexing stuck at Indexing … Docfetching finished](https://github.com/onyx-dot-app/onyx/issues/11379) | 2026-05-26 | 3 | 裏は完了、UI が Indexing のまま |
| Onyx | [Discussion #12071 Indexing stuck even there is neither document nor connector](https://github.com/onyx-dot-app/onyx/discussions/12071) | 2026-06-15 | 4 | 完了モニターが遅延。別コネクタを足すと Finished に進む |
| Onyx | [#8379 Indexing stuck at Initial/Scheduled](https://github.com/onyx-dot-app/onyx/issues/8379) | 2026-02-12 | 2 | キュー投入後、worker が消費せず 0 docs |
| Onyx | [#6660 Indexing Not Working (File & S3)](https://github.com/onyx-dot-app/onyx/issues/6660) | 2025-12-05 | — | scheduled のまま。UI の Reindex は動くが索引が進まない |
| Open WebUI | Reddit [Uploading files … inconvenient](https://www.reddit.com/r/OpenWebUI/comments/1xcdg67/uploading_files_to_knowledge_base_is_quite/) | 2026-10-22 | — | Uploading のまま。複数ファイルは1件しか見えず、タブを閉じてよいか分からない |
| Open WebUI | Reddit [v0.9.6 KB rework](https://www.reddit.com/r/OpenWebUI/comments/1tu84ne/v096_just_dropped_major_knowledge_base_rework/) | 2026-06-02 | — | 「単一ファイルの処理進捗がまだスピンだけ」 |
| AnythingLLM | [#6998 Embedding documents not moving](https://github.com/Mintplex-Labs/anything-llm/issues/6998) | 2026-11-04 | 6 | 埋め込みが動かない |
| AnythingLLM | [#6881 Voyage AI embedder never reports chunk progress](https://github.com/Mintplex-Labs/anything-llm/issues/6881) | 2026-10-28 | 0 | 進捗バーが動かない |
| AnythingLLM | Reddit [stuck on Documents page](https://www.reddit.com/r/LocalLLM/comments/1pkg7km/anythingllm_stuck_on_documents_page_and_my/) | 2025-12-11 | — | 大量ファイルでキューがなく、メンテも「4000 件一括は no queue」と認める |

### 2. 失敗理由が分からない／沈黙失敗

GitHub Search API（2026-11-20）:

| クエリ | total_count |
|---|---:|
| `repo:infiniflow/ragflow is:issue "parsing failed"` | **83** |
| `repo:Mintplex-Labs/anything-llm is:issue "Failed to embed" OR "failed to embed" OR "embed document failed"` | **60** |
| `repo:onyx-dot-app/onyx is:issue failed documents` | **51** |
| `repo:onyx-dot-app/onyx is:issue "failed documents" OR "index-attempt-errors"` | **20** |

公式が「理由を画面に出せ」と書いている例:

- Dify 新 API: 失敗時 `error_message` と `failure.action`（例: contact_admin）、`retryPolicy: manual`。[List Document Indexing Tasks](https://docs.dify.ai/en/api-reference/indexing-tasks/list-document-indexing-tasks)
- Microsoft: 2026-10 に「generic failure ではなく、原因と次の手を出す」診断を追加。[October 2026](https://techcommunity.microsoft.com/blog/microsoft-copilot-blog/microsoft-copilot-connectors-update-october-2026/4572240)。Error タブはコード・件数・ログ DL。[Monitor errors](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/error-responses)
- Onyx: 失敗文書 API 追加の動機が「今日は SSH してログを grep するしかない」。[PR #10204](https://github.com/onyx-dot-app/onyx/pull/10204)（2026-04-14）
- NN/g: エラーは平易な言葉・原因・回復手順。コードだけのメッセージはヒューリスティック #9 違反。[Error-Message Guidelines](https://www.nngroup.com/articles/error-message-guidelines/)、[Ten heuristics](https://nngroup.com/articles/ten-usability-heuristics/)、[Top 10 application-design mistakes](https://www.nngroup.com/articles/top-10-application-design-mistakes/)（「Something went wrong. Try again.」は stranded）

実例:

| 製品 | 出典 | 日付 | 内容 |
|---|---|---|---|
| Dify | [#30154](https://github.com/langgenius/dify/issues/30154) | 2025-12-25 | **No error messages in the dashboard** |
| Dify | [#18119 Error indexing knowledge](https://github.com/langgenius/dify/issues/18119) | 2025-04-15 | 複数ファイルはエラー、1件ずつだと **no error message** |
| Dify | [#30117 KB indexing stuck then Error](https://github.com/langgenius/dify/issues/30117) | 2025-12-24 | ログは 200 OK のみ。例外が見えない |
| RAGFlow | [#1828 Knowledge Graph mode failed](https://github.com/infiniflow/ragflow/issues/1828) | 2024-08-06 | **There is no error message at all**。何度も restart |
| RAGFlow | [#11605 Document parsing failed](https://github.com/infiniflow/ragflow/issues/11605) | 2025-11-29 | 一覧は成功、チャンク閲覧で "Document parsing failed"（プレビュー非対応 .doc） |
| AnythingLLM | [#6792 API upload reports success when workspace embedding fails](https://github.com/Mintplex-Labs/anything-llm/issues/6792) | 2026-10-21 | 成功と出して埋め込み失敗 |
| AnythingLLM | changelog [v1.18.0](https://docs.anythingllm.com/changelog/v1.18.0) | 2026-11-17 | 「Confluence import errors are now shown instead of failing silently」「Embedding errors are now shown when drag-and-drop fails」→ 以前は沈黙失敗だった、という公式の自己申告 |
| PipesHub | [#2997 Connector HTTP client: timeouts surface as empty-message errors and are never retried — silent content loss](https://github.com/pipeshub-ai/pipeshub-ai/issues/2997) | 2026-08-19 | コメント 2。タイムアウトが空メッセージになり **静かに欠ける** |
| Open WebUI | Reddit [failed to add file](https://www.reddit.com/r/OpenWebUI/comments/1lbqtj0/openwebui_failed_to_add_file/) | 2025頃 | 失敗バブルがすぐ消え、理由が見えない。サークルが回り続ける |

### 3. 再処理・リトライできない（error でない stuck は特に）

GitHub Search API（2026-11-20）:

| クエリ | total_count |
|---|---:|
| `repo:langgenius/dify is:issue retry document knowledge` | **163**（やや広い） |
| `repo:infiniflow/ragflow is:issue reparse OR "re-parse" OR "retry parse"` | **271**（やや広い） |
| `repo:onyx-dot-app/onyx is:issue retry indexing connector` | **29** |
| `repo:pipeshub-ai/pipeshub-ai is:issue reindex` | **13** |

公式:

- Dify: Retry ボタンは **error 文書があるときだけ**表示。[#7354 The retry index button?](https://github.com/langgenius/dify/issues/7354)（2024-08-16）。新 API に Retry Indexing Task。[docs](https://docs.dify.ai/en/api-reference/indexing-tasks/retry-indexing-task)
- RAGFlow: Parse Again の公式シナリオ（設定変更、ソース更新、結果がおかしい）。[Files](https://ragflow.io/docs/files_dataset_document_management)。API で進捗 0 または 1 の停止は拒否。[Reddit: cancel parsing](https://www.reddit.com/r/Rag/comments/1hh0ch5/trying_to_cancel_parsing_through_ragflow_api/)（2024-12-18）
- Onyx: 失敗文書の Retry と Full Re-index。[overview](https://docs.onyx.app/admins/connectors/overview)
- Microsoft: オンデマンド full/incremental。[Manage connectors](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/manage-connector)

実例:

| 製品 | 出典 | 日付 | 内容 |
|---|---|---|---|
| Dify | [#42104 Feature: Retry failed document indexing through the Knowledge Service API](https://github.com/langgenius/dify/issues/42104) | 2026-09-10 | コメント 0。API 経由リトライの要望 |
| Dify | [#30237 STATUS stuck in Queuing … Re-trigger](https://github.com/langgenius/dify/issues/30237) | 2025-12-27 | SQL で error にして Retry。通常の Retry では Queuing に戻るだけ |
| Dify | [#28329 埋め込みモデル変更後、再索引失敗](https://github.com/langgenius/dify/issues/28329) | 2025-11-18 | **バッチ修復なし。1件ずつ pause/resume** |
| Dify | [#28184 documents are always in the index](https://github.com/langgenius/dify/issues/28184) | 2025-11-13 | モデル変更後、個別 pause/resume。一括不可 |
| Dify | [#11746](https://github.com/langgenius/dify/issues/11746) | 2024-12-17 | 失敗後に Save & Process すると "Document is not available"。archive/unarchive で "being indexed" |
| Dify | [#3909](https://github.com/langgenius/dify/issues/3909) | 2024-04-26 | 「索引失敗後に手動リトライを」 |
| RAGFlow | [#7838 Unable to Re-parse Failed Documents via Python API](https://github.com/infiniflow/ragflow/issues/7838) | 2025-05-25 | コメント 4 |
| Open WebUI | [#28106 Reindex … never rebuilds per-file collections](https://github.com/open-webui/open-webui/issues/28106) | 2026-08-04 | Reindex 成功と出るが単一ファイル添付が空 |
| PipesHub | [#5717 "Manual index" and record-group reindex index records the connector's indexing filters exclude](https://github.com/pipeshub-ai/pipeshub-ai/issues/5717) | 2026-11-12 | 手動再索引がフィルタを無視 |

### 4. どの文書が入っているか分からない／一覧と実索引がずれる

GitHub の狭いヒットはテーマ1–3より少ない。公式は「特定文書の検証」を独立機能にしている。

公式:

- Glean Access Verification: not crawled / crawled but not indexed / indexed but no permission / excluded。[docs](https://docs.glean.com/connectors/connectors-health-index)、[Access verification](https://docs.glean.com/administration/search/access-verification)
- Microsoft Index browser + Statistics（discovered / fully indexed / partially indexed / out of sync / failed）。[View connection details](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/view-details)
- Dify: 文書リストを `queuing | indexing | paused | error | available | disabled | archived` でフィルタ。[List documents](https://docs.dify.ai/api-reference/%E6%96%87%E6%A1%A3/%E8%8E%B7%E5%8F%96%E7%9F%A5%E8%AF%86%E5%BA%93%E3%81%AE%E6%96%87%E6%9B%B8%E3%83%AA%E3%82%B9%E3%83%88)
- RAGFlow: `include_parsing_status` で unstart/running/cancel/done/fail 件数。[HTTP API](https://ragflow.io/docs/http_api_reference)
- Open WebUI: 処理完了前のファイルは中身が空。[docs](https://docs.openwebui.com/llms-full.txt)

実例:

| 製品 | 出典 | 日付 | 内容 |
|---|---|---|---|
| Dify | [#29158 Searching the knowledge base does not yield relevant results](https://github.com/langgenius/dify/issues/29158) | 2025-12-05 | アップロード後、検索できない。モデル切替＝再索引で解消 |
| Open WebUI | Reddit [Files parsed … model doesn’t see them](https://www.reddit.com/r/OpenWebUI/comments/1mo2o4b/help_files_are_parsed_and_uploaded_but_the_model/) | 2025-08-12 | パース成功・UI で読めるが、モデルが使わない |
| Microsoft | [Monday.com troubleshooting](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/monday-troubleshooting) | 2026-09-25 | Ready でも権限不足で欠ける |
| Microsoft | [SharePoint troubleshooting](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/sharepoint-server-troubleshooting) | 2026-09-22 | Ready だが多数未索引（プロキシ） |
| Glean | [Crawling FAQ](https://docs.glean.com/connectors/crawling-faq) | 2026-10-08 | 「Job in progress は数日続くのが普通」 |

### 5. 大量ファイルで遅い／進捗が粗い

GitHub Search API:

| クエリ | total_count |
|---|---:|
| `repo:langgenius/dify is:issue "slow" indexing knowledge` | **32** |
| `repo:Mintplex-Labs/anything-llm is:issue progress embed document` | **24** |
| `repo:open-webui/open-webui is:issue "Reindex Knowledge"` | **20** |

公式:

- RAGFlow: GPU、RAPTOR/GraphRAG/Auto-keyword オフ、PDF は Naive。[Accelerate indexing](https://ragflow.io/docs/v0.20.5/accelerate_doc_indexing)
- AnythingLLM: フォルダ 100+ 件で全ファイル表示。[v1.18.0](https://docs.anythingllm.com/changelog/v1.18.0)。ストリーム埋め込み。[v1.12.1](https://docs.anythingllm.com/changelog/v1.12.1)
- Open WebUI: ブラウザ内 Sync Directory は大規模で遅く進捗が少ない、という公式の自己評価。[oikb](https://docs.openwebui.com/llms-full.txt)
- Glean: 大規模は数日。メトリクスは **1時間ごと**。[Connect Data Sources](https://docs.glean.com/get-started/setup/connect-data-sources)
- NN/g: 複雑アプリは経過時間・残りステップ。[complex applications](https://www.nngroup.com/articles/usability-heuristics-complex-applications/)

実例:

| 製品 | 出典 | 日付 | 内容 |
|---|---|---|---|
| Dify | [Discussion #6187 知識庫索引緩慢](https://github.com/langgenius/dify/discussions/6187) | — | 800KB CSV で 10–20 分、時々失敗 |
| Dify | [#5087 cannot be properly completed](https://github.com/langgenius/dify/issues/5087) | 2024-06-11 | **10MB 超で stuck**。再起動しても終わらない |
| Dify | [#45365 indexing hangs at ~90% with Milvus](https://github.com/langgenius/dify/issues/45365) | 2026-11-03 | コメント 1 |
| Open WebUI | [#30003 Unindexed get_pending_files_for_knowledge](https://github.com/open-webui/open-webui/issues/30003) | 2026-09-14 | コメント 2。pending が残ると KB ページが DB を飽和。**stuck pending が前提** |
| Open WebUI | Reddit [Optimizing Importing of Large Files](https://www.reddit.com/r/OpenWebUI/comments/1iuwgju/optimizing_importing_of_large_files_in_knowledge/) | 2025-02-21 | 3.5MB PDF で数分、CPU 張り付き |
| AnythingLLM | Reddit [stuck on Documents](https://www.reddit.com/r/LocalLLM/comments/1pkg7km/anythingllm_stuck_on_documents_page_and_my/) | 2025-12-11 | 数千ファイル。メンテ「正確にその用途向けに作り直している」 |
| AnythingLLM | [#5000 GPT4All-style LocalDocs … multiple folders](https://github.com/Mintplex-Labs/anything-llm/issues/5000) | 2026-02-13 | コメント 8。フォルダ一括索引の要望 |

### 6. 削除が反映されない／prune が壊れる

狭いクエリの件数はテーマ1より小さい。個別 Issue と公式 FAQ が主証拠。

| 製品 | 出典 | 日付 | 内容 |
|---|---|---|---|
| Dify | [#40457 Weaviate: deleting a document never removes its vectors](https://github.com/langgenius/dify/issues/40457) | 2026-08-10 | コメント 4 |
| Dify | [#38518 Deleting a KB while indexing leaves orphaned segments](https://github.com/langgenius/dify/issues/38518) | 2026-07-07 | コメント 7 |
| Dify | [#42641 Deleting a document orphans segment-attachment vectors](https://github.com/langgenius/dify/issues/42641) | 2026-09-21 | コメント 1 |
| Dify | [#44910 Re-uploading … can delete its vectors and leave it "waiting"](https://github.com/langgenius/dify/issues/44910) | 2026-10-27 | コメント 2 |
| Open WebUI | [#34007 option to remove a file's vectors when deleted (GDPR)](https://github.com/open-webui/open-webui/issues/34007) | 2026-11-10 | コメント 2。Chroma/pgvector は削除時にベクトルが残る |
| Onyx | [#16221 SharePoint prune deletes every document when listing returns empty](https://github.com/onyx-dot-app/onyx/issues/16221) | 2026-10-18 | コメント 3 |
| Onyx | [#1378 Connectors Remain Stuck in 'Deleting'](https://github.com/onyx-dot-app/onyx/issues/1378) | 2024-04-25 | UI から外せない |
| Glean | [Crawling FAQ: Why is a deleted document still appearing?](https://docs.glean.com/connectors/crawling-faq) | 2026-10-08 | 伝播遅延。イベント欠落時は full crawl 待ち |
| Microsoft | [Manage connectors](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/manage-connector) | 2026-11-13 | 28 日未再発見で自動削除。除外は接続削除＋作り直し、という記述あり（2026-10 更新で編集可能になった、と同社ブログ） |
| AnythingLLM | 公式: ディレクトリ全体の watch は不可。[Live document sync](https://docs.anythingllm.com/beta-preview/active-features/live-document-sync) | 2026-11-18 | ファイル単位。削除で unwatch |

### 7. 通知がない

OSS の GitHub で `notification` 系は今回、レート制限とヒットの質で **件数を確報できない（未確認）**。商用側は公式機能として存在する。

- **Glean**: コネクタ失敗アラートはデフォルト ON、解決まで毎日。無効化不可。[Alerts](https://docs.glean.com/connectors/connectors-health-index)
- **Microsoft**: 恒久失敗 → サービス正常性 + 管理センターの通知バー（6日、履歴30日）。メールは Service health の「Issues that require action」。[Manage connectors](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/manage-connector)。2026-10 にライフサイクルのプロアクティブメール。[October 2026](https://techcommunity.microsoft.com/blog/microsoft-copilot-blog/microsoft-copilot-connectors-update-october-2026/4572240)
- **NN/g**: 緊急度と要アクションで indicator / validation / notification を使い分ける。[Indicators, Validations, and Notifications](https://www.nngroup.com/articles/indicators-validations-notifications/)
- OSS: 画面を開き続けてポーリングする前提が多い（Dify の indexing-status ポーリング、Open WebUI の process/status、RAGFlow の進捗バー）。**推測**: 社内 Electron でも、完了・失敗を OS 通知しないと非エンジニアは画面を開きっぱなしにする。

### 8. フォルダ指定・追加・継続監視

対象アプリ（フォルダ指定が主）に直結する要望。

| 製品 | 出典 | 日付 | コメント | 内容 |
|---|---|---|---:|---|
| AnythingLLM | [#1873 Auto-add and Watch Folder](https://github.com/Mintplex-Labs/anything-llm/issues/1873) | 2024-07-15 | — | フォルダ監視。メンテ: **1ファイルずつ watch**。1万件一括は負荷でやらない |
| AnythingLLM | [#3561 Auto-Add ALL Docs in a Given Folder](https://github.com/Mintplex-Labs/anything-llm/issues/3561) | 2025-03-28 | 9 | 毎日増えるコーパスを自動追加したい |
| AnythingLLM | [#5000 one-click indexing of multiple folders](https://github.com/Mintplex-Labs/anything-llm/issues/5000) | 2026-02-13 | 8 | OS のフォルダツリーを一発索引 |
| AnythingLLM | 公式 watch | [docs](https://docs.anythingllm.com/beta-preview/active-features/live-document-sync) | ディレクトリ watch は未提供。チェックは時間単位。アプリ起動中のみ |
| Open WebUI | 公式 directory sync / oikb | [v0.9.6 Reddit](https://www.reddit.com/r/OpenWebUI/comments/1tu84ne/v096_just_dropped_major_knowledge_base_rework/)、[oikb](https://docs.openwebui.com/llms-full.txt) | フォルダ同期・差分・削除反映を後から足している |
| Dify | 公式 | [pipeline upload](https://docs.dify.ai/zh/use-dify/knowledge/knowledge-pipeline/knowledge-pipeline-orchestration) | ファイルまたはフォルダのドラッグ。バッチ上限あり |
| PipesHub | [#5740 failed filter read makes a connector sync as if it had no filters](https://github.com/pipeshub-ai/pipeshub-ai/issues/5740) | 2026-11-13 | 3 | 範囲指定が壊れると全件入る |

### 9. 設定変更後の再索引（埋め込みモデル・チャンク）

公式が「後から変えると全再索引」と警告する。

- Dify: モデル変更は全文書再索引。[Create Agent KB](https://docs.dify.ai/en/cloud/use-dify/knowledge-base/create-knowledge-base)。利用者: [#28329](https://github.com/langgenius/dify/issues/28329)、[#28184](https://github.com/langgenius/dify/issues/28184) で **一括修復できない**
- Onyx: Index Settings で再索引進捗（waiting / in progress / completed / failed / paused）。失敗が同じ地点で続くと pause。**Re-index Attention** でエラーを見て Resume。[Index Settings](https://docs.onyx.app/admins/advanced_configs/search_configs)
- Open WebUI: Reindex が PDF ページメタを捨てる [#33909](https://github.com/open-webui/open-webui/issues/33909)（2026-11-08、コメント1）、全文書を再抽出する [#34066](https://github.com/open-webui/open-webui/issues/34066)（2026-11-10、コメント4）
- AnythingLLM Reddit: モデル切替後は vector DB リセットとキャッシュ解除が必要。[CPU bottleneck](https://www.reddit.com/r/u_EDLLT/comments/1eq82zd/solution_anythingllm_cpu_bottleneck_problem_when/)（2024-08-12）

### 10. 一時停止・キャンセル

公式はある。利用者は「止められない／止めると壊れる」側。

- RAGFlow: 赤い×で stop、その後 re-parse。[#9466](https://github.com/infiniflow/ragflow/issues/9466)。API は進捗 0/1 で cancel 拒否
- Dify: paused 状態、pause/resume。[#29901](https://github.com/langgenius/dify/issues/29901)
- Microsoft: Pause しても検索は残る。[Manage connectors](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/manage-connector)
- Onyx: Pause Indexing & Syncs。索引済みは検索可能。[overview](https://docs.onyx.app/admins/connectors/overview)

---

## 製品別：画面を開く頻度の整理（公式＋利用者）

**推測**（公式の操作フローからの合成。実測の開封頻度データは見つからず **未確認**）:

| タイミング | 頻度の目安（推測） | 根拠 |
|---|---|---|
| 初期設定・フォルダ指定 | 導入時＋ソース追加のたび | 全製品のセットアップ手順 |
| 初回同期の監視 | 導入後数時間〜数日、繰り返し | Glean「onboarding 中は Crawl Rate」、MS「Ready まで待て」 |
| 失敗・stuck | 障害のたび。OSS ではこれが Issue の大半 | 上記テーマ1–3 |
| 文書追加 | コンテンツが増えるたび | Dify Add File、OWUI upload、AnythingLLM embed |
| 削除確認 | 削除・権限変更のあと | Glean FAQ、MS 28日、Onyx prune |
| 日常の鮮度確認 | 商用は日次メトリクス／アラート。OSS は画面を開かないと分からない | Glean Change Rate、MS Last sync、OSS はポーリング |
| 設定変更・再索引 | モデル／チャンク変更時（稀だが高コスト） | Dify / Onyx / OWUI |

---

## このアプリの利用者が画面でやりたいこと（頻度×重要度）

対象は「検索しない取り込み管理アプリ（Windows Electron、非エンジニア含む）」。候補は上の一次情報に URL を付けた。上位ほど、公式が独立画面を用意し、かつ OSS Issue が厚い。

### 1. 取り込みが終わったかを、止まらずに見ること（最頻・最重要）

やりたいこと: フォルダ指定のあと、「今どこまで終わったか」「まだ動いているか」「完了したか」が一目で分かる。10秒超ならパーセントかステップ。Stuck は error と区別する。

根拠: Glean [When to investigate](https://docs.glean.com/connectors/connectors-health-index)、MS [October 2026 crawl progress](https://techcommunity.microsoft.com/blog/microsoft-copilot-blog/microsoft-copilot-connectors-update-october-2026/4572240)、Dify 公式の状態機械 [API](https://docs.dify.ai/en/api-reference/guides/knowledge)、NN/g [progress indicators](https://www.nngroup.com/articles/progress-indicators/)、Dify 115 件 `stuck indexing`、RAGFlow 135 件 `parsing stuck`。

### 2. 失敗したら、理由が読め、その場で再処理できること

やりたいこと: 失敗ファイルが一覧になる。理由は平易な日本語。次のアクション（再試行／設定を直す／そのファイルをスキップ）がボタンになる。SSH や Docker ログを要求しない。

根拠: NN/g [heuristic 9](https://nngroup.com/articles/ten-usability-heuristics/)、[error-message guidelines](https://www.nngroup.com/articles/error-message-guidelines/)、MS Error タブと 2026-10 の文脈付き診断、Onyx [失敗文書 Retry](https://docs.onyx.app/admins/connectors/overview) と [PR #10204](https://github.com/onyx-dot-app/onyx/pull/10204)、Dify [#30154 エラーなし](https://github.com/langgenius/dify/issues/30154)、[#7354 Retry は error のときだけ](https://github.com/langgenius/dify/issues/7354)、AnythingLLM [沈黙失敗を後から表示するようにした changelog](https://docs.anythingllm.com/changelog/v1.18.0)。

### 3. 取り込むフォルダを指定し、追加・除外を後から変えられること

やりたいこと: エクスプローラ相当でフォルダを選ぶ。サブフォルダを含む。後からフォルダを足す／外す。範囲指定が壊れて全件入る事故を防ぐ。

根拠: このアプリの要件そのもの。AnythingLLM [#3561](https://github.com/Mintplex-Labs/anything-llm/issues/3561)、[#1873](https://github.com/Mintplex-Labs/anything-llm/issues/1873)、[#5000](https://github.com/Mintplex-Labs/anything-llm/issues/5000)。PipesHub [#5740 フィルタ失敗で全件](https://github.com/pipeshub-ai/pipeshub-ai/issues/5740)。OWUI が後から directory sync を足した [v0.9.6](https://www.reddit.com/r/OpenWebUI/comments/1tu84ne/v096_just_dropped_major_knowledge_base_rework/)。

### 4. 「どのファイルが入っているか／入っていないか」をファイル名で確認できること

やりたいこと: 指定フォルダのファイル一覧と、成功・失敗・未処理の対応。特定ファイルを検索して「入っている／まだ／失敗」が分かる（Glean Access Verification、MS Index browser のローカル版）。

根拠: [Glean Access Verification](https://docs.glean.com/administration/search/access-verification)、[MS Index browser](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/indexed-content)、Dify の status フィルタ、RAGFlow の文書一覧、Open WebUI「処理完了まで中身が空」。

### 5. 大量ファイルでも、件数が進み、途中で閉じても再開できること

やりたいこと: 件数（済／全／失敗）。1ファイルの細かい％より「何件目」。タブ／アプリを閉じてもキューが残る。一括でキューが溶けるのを避ける。

根拠: AnythingLLM Reddit [no queue at 4000 files](https://www.reddit.com/r/LocalLLM/comments/1pkg7km/anythingllm_stuck_on_documents_page_and_my/)、[v1.12.1 streamed embedding、ページを離れても進捗維持](https://docs.anythingllm.com/changelog/v1.12.1)、OWUI Reddit [タブを閉じてよいか分からない](https://www.reddit.com/r/OpenWebUI/comments/1xcdg67/uploading_files_to_knowledge_base_is_quite/)、[#30003 pending が残ると DB 飽和](https://github.com/open-webui/open-webui/issues/30003)。

### 6. 失敗・Stuck を一括で再処理できること（1件ずつの pause/resume を避ける）

やりたいこと: 失敗だけ Retry。Stuck（error でない）も「強制再実行」。モデル／設定変更後の一括再索引と、失敗1件の再実行を分ける。

根拠: Dify [#28184 一括不可](https://github.com/langgenius/dify/issues/28184)、[#28329](https://github.com/langgenius/dify/issues/28329)、[#29901 force re-index なし](https://github.com/langgenius/dify/issues/29901)、Onyx の失敗文書 Retry vs Full Re-index、RAGFlow Parse Again。

### 7. フォルダ内の追加・更新・削除が、索引に反映されたかを確認できること

やりたいこと: 新規ファイルが載ったか。更新されたか。ゴミ箱に入れたファイルが索引から消えたか。反映までの目安時間。

根拠: Glean [削除 FAQ](https://docs.glean.com/connectors/crawling-faq)、Onyx Prune Every デフォルト 7 日、[#16221 prune が全削除](https://github.com/onyx-dot-app/onyx/issues/16221)、Dify 削除後にベクトル残留 [#40457](https://github.com/langgenius/dify/issues/40457)、OWUI GDPR [#34007](https://github.com/open-webui/open-webui/issues/34007)、AnythingLLM はファイル単位 watch のみ。

### 8. 終わった・失敗したことを、画面を開いていなくても知ること

やりたいこと: 完了／失敗の OS 通知またはメール。失敗は繰り返し。成功は初回同期と手動実行時。

根拠: Glean 必須アラート、MS サービス正常性＋2026-10 メール。NN/g [notifications](https://www.nngroup.com/articles/indicators-validations-notifications/)。OSS はポーリング前提で、非エンジニア向け社内アプリでは不足、というのが **推測**。

### 9. 危険な設定変更の前に、影響範囲（全再索引になるか）が分かること

やりたいこと: 埋め込みモデルやチャンク変更が「全ファイル再処理」になるなら、件数と時間の見積もり。実行中はバナーで進捗。失敗したらそのファイルから Resume。

根拠: Dify [小さいうちにモデルを決めよ](https://docs.dify.ai/en/cloud/use-dify/knowledge-base/create-knowledge-base)、Onyx [Re-index Attention](https://docs.onyx.app/admins/advanced_configs/search_configs)、MS [編集が full crawl を起こしうる](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/manage-connector)。

### 10. 走っている取り込みを止めて、後で再開できること

やりたいこと: キャンセルは「今のファイルで止める」。既に成功した分は残す。止められない／止めると全体が死ぬ、を避ける。

根拠: RAGFlow [#9466 再起動以外に復帰できない](https://github.com/infiniflow/ragflow/issues/9466)、API cancel 制限、MS/Onyx の Pause でも検索は残る設計。

---

## 画面要件への読み替え（短い）

社内 Electron の取り込み管理は、Glean / Copilot 管理画面の「コネクタ」と、Dify / RAGFlow の「文書リスト」の交差点になる。検索 UI は不要。非エンジニアが開く主目的は次の4つに収束する。

1. **フォルダを選ぶ**  
2. **終わるのを待つ（動いている証拠つき）**  
3. **失敗を読んで、ボタンでやり直す**  
4. **入った／消えたをファイル名で確かめる**

1 はセットアップと追加のとき。2–4 は初回同期中と障害時に高頻度。通知（8）は画面を開く回数を減らす。設定・一括再索引（9）は低頻度・高損害。

NN/g の一次原則は2つだけで足りる。状態を隠さない（[heuristic 1](https://www.nngroup.com/articles/visibility-system-status/)）。失敗したら原因と直し方を出す（[heuristic 9](https://www.nngroup.com/articles/error-message-guidelines/)）。OSS の Issue の大半は、この2つが欠けたときの報告である。

---

# Part B: 調査2〜5
## 調査日・方法

- **調査日:** 2026-11-20
- **対象:** 調査2（同期・バックアップ常駐アプリ + Microsoft デザインガイド）、調査3（状態の見せ方の UX 研究）、調査4（余白・密度・黄金比）、調査5（AI 生成 UI / vibe-coded UI 批判）
- **方法:** ライブ Web 検索のあと、公式ヘルプ・Microsoft Learn・Fluent 2・NN/g・vscode `main` の raw ソース・査読論文・HN / Reddit / X をページ本文まで開いて読んだ。`web_fetch` は support.google.com / nngroup.com / fluent2.microsoft.design / support.microsoft.com / help.dropbox.com で SSRF 拒否されたため、`open_page` で本文を取得した。
- **件数の数え方:** 自分で表の行を数えたものだけ書く。著者のコーパス件数は「著者の申告」と明記し、再集計していない。
- **除外:** `https://prg.sh/ramblings/Why-Your-AI-Keeps-Building-the-Same-Website.html` は 2026-11-20 に 404。Medium の Laith Aljunaidy 記事も同日 404。どちらも根拠に使わない。File History のトレイ／再試行／一時停止、Drive のトレイ字形一式は公式ページに無いので発明しない。

---

## 調査2：同期・バックアップ常駐アプリ

5製品はいずれも「常駐トレイ + 状態の一言 + 失敗一覧 + 一時停止（File History を除く）+ 設定」で、検索 UI は主目的ではない。

### Google Drive for desktop

公式ページはトレイの「回転／塗りつぶし／一時停止」字形一式を列挙していない。**未確認**。確認できたのは次だけ。

**再設計ホームページ**（[Learn how to use the redesigned Drive for desktop](https://support.google.com/drive/answer/16035364)）

原文要点:

- 「The new "Sync status" tile on your homepage displays your recently synced files and current syncing activity. It replaces the previous "Activity" view.」
- 詳細は左ナビまたは 「View all sync activity」
- 「Important updates, like time-sensitive sync errors, show in your notifications.」
- 「You can pause or resume the sync process of Drive for desktop at any time with the conveniently placed Pause button.」

**チートシート**（[Drive for desktop cheat sheet](https://support.google.com/a/users/answer/10096660)）

原文要点:

- アップロード完了は **Upload complete**
- ファイルアイコン: Sync（未アップロード／処理中。一時停止時もこのアイコン）、Done（成功）、キュー件数アイコン
- オフライン: 緑の Offline pin／Online status
- 「In Settings you can Pause Syncing, modify Preferences, and view the Error list.」
- 「View notifications.」「Activity of synced files is shown by default.」

**設定**（[Customize Drive for desktop settings](https://support.google.com/drive/answer/13470231)）に見出し **Pause sync** がある。本文の zippy は取得時に折りたたまれ、一時停止の分数は公式本文から **未確認**。

**失敗と再処理**（[Fix problems in Drive for desktop](https://support.google.com/drive/answer/2565956?hl=en)）

- 見出しに 「Can't sync file/ folder - moved to “Lost & Found”」
- 基本手順: 要件確認、ネット、再起動、アカウント切断／再接続、再インストール

[Google One 版の同記事](https://support.google.com/googleone/answer/2565956?hl=en) は Lost and Found を具体化している。

原文要点:

- 「The unsynced file is copied to a “Lost and Found” folder on your hard drive. When this occurs, there is a notification shown with a link to open the “Lost and Found” folder.」
- Windows: `C:\Users\<username>\AppData\Local\Google\DriveFS\lost_and_found\<account_token>`
- 「Move these files back into My Drive to retry syncing」

コミュニティ投稿（[Files not synced / Lost and Found](https://support.google.com/drive/thread/364928738/onscreen-message-from-google-drive-about-lost-and-found-folder?hl=en)、2025-08-13）はポップアップ原文を引用する: 「3 items couldn't be synced and were moved to the "Lost and Found" folder. To stop seeing this message, move the files out of "Lost and Found".」

### OneDrive

**トレイ／オーバーレイアイコン**（[What do the OneDrive icons mean?](https://support.microsoft.com/en-us/onedrive/what-do-the-onedrive-icons-mean)）

原文要点:

- 青 i: 機能や推奨アクションのメッセージ。クラウドアイコンを選ぶ
- 赤丸白クロス: 同期できない。通知領域アイコンを選んで詳細
- 灰色に取り消し線: 未サインイン／セットアップ未完了
- 一時停止記号: 「your files aren't currently syncing」。**Resume syncing**
- 黄警告三角／茶警告: アカウント要対応。activity center に警告
- 赤「進入禁止」: アカウント凍結
- 回転矢印: 同期中。長時間は 「Processing changes」
- ファイル: 緑丸白チェック（Always keep on this device）、白丸緑チェック（ローカル利用可）、青雲（オンラインのみ）

この公式アイコンページは、ホバー文言 「Your files are up to date」 を書いていない。**未確認（公式アイコン頁）**。

**一時停止**（[How to Pause and Resume OneDrive Sync](https://support.microsoft.com/en-us/onedrive/how-to-pause-and-resume-onedrive-sync)）

原文要点:

- 従量課金や低速回線、または 「Processing changes」 が長いときに pause
- トレイを右クリックし **2 / 8 / 24 hours**。アイコンが Paused になる
- バッテリーセーバーや従量ネットワークでは自動 pause
- 個人と仕事用は独立に pause/resume
- 再開: 一時停止アイコン → activity center の黄色ボックス等

ホバー 「Up to date」 は公式サポート本文ではなく、Microsoft Q&A で確認した。Rob Nicholson（2026-03-26）: ホバーは 「Up to date」、クリックすると約 50GB アップロード中、別表現 「Your files are all synced」 もある（[Incorrect OneDrive status](https://learn.microsoft.com/en-us/answers/questions/5838820/incorrect-onedrive-status-doesnt-show-activity)）。Microsoft スタッフ Tamara-Hu（2026-03-29）: 「the tray icon may temporarily show “Up to date” even though activity is still ongoing in the background.」 取り込み管理では、ホバー一言より **Activity Center 相当の一覧を正** にする根拠になる。

### Dropbox

**状態の一言**（[How to check if your files and folders are syncing](https://help.dropbox.com/sync/check-sync-status)、Updated Aug 14, 2026）

トレイクリック後、ウィンドウ下部の状態:

- Indexing
- Syncing [file name]
- Syncing [x] files
- Syncing paused until [x]
- **Your files are up to date**
- Starting
- Connecting components（macOS File Provider、チーム）
- Requesting access to encrypted folders（チーム）
- **[x] files are unable to sync** → **See issues**

**一時停止**（[How to pause and resume file syncing](https://help.dropbox.com/sync/pause-resume)、Updated Dec 18, 2024）

- **30 minutes / 1 hour / Until tomorrow / Indefinitely**
- 状態テキストの下矢印から選ぶ。再開時刻のメッセージが出る
- 例: **File sync and backups paused until 3:22 PM** → **Resume**
- 一時停止中も変更通知は来るが、PC フォルダには反映されない
- トレイアイコンに pause ボタンが乗る

**トレイアイコン**（[Dropbox sync icons in the desktop app for Windows](https://help.dropbox.com/sync/sync-icons-windows)、Updated Sep 15, 2026）

| トレイ | 状態 |
| --- | --- |
| 塗りつぶし黒、付加なし | Fully synced |
| 白矢印の回転 | Sync in progress |
| 白 pause | Syncing paused |
| 灰色 | Not connected（起動中／終了中も） |
| 灰色 + X | An error has occurred |
| 赤丸数字 | Unread notifications |
| 灰色 + ZZ | Snooze notifications |
| カメラ | Camera uploads |

ファイル: 緑丸チェック（明示オフライン）、雲（オンラインのみ）、白丸緑枠チェック、回転矢印、赤 X、灰色マイナス（ignored）。アプリ左下も完了時 **Your files are up to date**。

### Windows ファイル履歴

公式コンシューマヘルプ（[Backup and restore with File History](https://support.microsoft.com/en-us/windows/experience/backup-recovery/backup-and-restore-with-file-history)）は **Turn on / Select drive / Restore previous versions** まで。トレイアイコン、失敗一覧、再試行、一時停止は公式本文に無い。**未確認**。

確認できた画面要素:

- Control Panel → System and Security → **Save backup copies of your files with File History** → **Turn on**
- ドライブ未選択なら **Select drive**
- 既定対象: Documents, Pictures, Videos, Desktop。他フォルダはライブラリへ
- 復元: フォルダを右クリック → **Restore previous versions**。Open in File History / Restore / Restore to...

**詳細設定の既定**はコンシューマヘルプではなく Microsoft Learn 研修（[Explain file history](https://learn.microsoft.com/en-us/training/modules/employ-file-recovery-windows-client/3-explain-file-history)、検索スニペット 2026-11-20）:

- 「Windows saves modified files every hour and keeps file versions indefinitely by default.」
- Control Panel または Settings → Update & security → Backup → More options。頻度と保持期間、除外、手動開始

Q&A は Advanced settings の **Save copies of files**、**Keep saved versions**、**Event Logs** に言及する（[Windows 10 Backup with File History](https://learn.microsoft.com/en-us/answers/questions/2777352/windows-10-backup-with-file-history)）。2026-09 前後の 「Reconnect your drive」／バックアップ失敗は既知の不具合として扱われ、KB5124010 が案内されている（[Windows 11 File History recopies unchanged files](https://learn.microsoft.com/en-us/answers/questions/6014106/windows-11-file-history-recopies-unchanged-files-w)）。取り込み管理では「最終成功時刻が動かない」をエラーとして扱う根拠になる。**推測:** ファイル履歴は常駐トレイ型ではなくコントロールパネル型。

### Backblaze

**画面構成**（[Windows Settings and System Preferences](https://www.backblaze.com/computer-backup/docs/windows-settings-and-system-preferences)、Updated 30 May 2024）

- 起動: Start Menu または **System Tray**（時計左）。Win8: 通知領域を展開 → 右クリック → **Backblaze Control Panel**
- **Backup Now**: スケジュールに応じて再開または開始
- **Restore Options**
- **Settings**
- **You are backed up as of**: 「the 'remaining files' reached '0 files' at that time」。全ドライブ走査に平均 1–2 時間。外付けは 1–120 分でスケジュール。未検出の新規・変更があり得る。アップロード不能は [Issues Report](https://help.backblaze.com/hc/en-us/articles/217666698-Issues-Report)
- **Selected for Backup**: 件数とサイズ
- **Backup Schedule**
- **Remaining Files**: キューの件数とサイズ

**Issues**（[How to Use the Reports and Issues Options (Windows)](https://www.backblaze.com/computer-backup/docs/use-the-reports-and-issues-options-windows)、Updated 10 Jun 2024）

- Files Scheduled for Backup: 進行中／一時停止ならフルパス。最新なら空
- Reports: ファイル種別
- Issues: 「the file that cannot be backed up and the reason」。権限（System に Read）、Temporary File Busy、Temporary Drive Unplugged

**一時停止の意味**（[How to Resolve a Paused Backup](https://www.backblaze.com/computer-backup/docs/resolve-a-paused-backup)、Updated 01 Nov 2024）: Remaining Files が 0 でも Initial Backup のまま pause することがある。読めない／他アプリが開いている／外付け未接続。後で再試行する。ユーザー操作の「一時停止ボタン」の公式説明は薄い。**未確認（ユーザー主導 Pause の UI ラベル）**。

**スケジュール**（[How to Set a Backup Schedule (Windows)](https://www.backblaze.com/computer-backup/docs/set-a-backup-schedule-windows)、Updated 18 Mar 2024）

- **Continuous (Recommended)**: 約1時間ごと。Backup Now は pause の再開のみ
- **Once Per Day**
- **Only When I Click Backup Now**

**警告**（[How to Configure General Settings (Windows)](https://www.backblaze.com/computer-backup/docs/configure-general-settings-windows)）: **Warn me when not backed up for** はポップアップ。進行中でも未完了なら出る。Select Hard Drives に最終バックアップ日時。

### 5製品の共通パターン（公式で確認できたもの）

| 要素 | Drive | OneDrive | Dropbox | File History | Backblaze |
| --- | --- | --- | --- | --- | --- |
| トレイ | メニューから Settings / Pause / Error list。字形一式は未確認 | クラウド + 赤X / pause / 警告 / 回転 | 黒／回転／pause／灰／X | 未確認 | System Tray → Control Panel |
| 一言 | Sync status タイル。完了は Upload complete | 公式アイコン頁に完了一言なし。Q&A で hover 「Up to date」 | **Your files are up to date** | なし（Control Panel） | **You are backed up as of** |
| 失敗一覧 | Error list、Lost and Found、通知 | activity center、Fix sync problems | **See issues** | Event logs（Q&A／Learn）。公式コンシューマ本文は薄い | **Issues** タブ |
| 再試行 | Lost and Found を My Drive に戻す、再起動、再接続 | Resume、トラブルシュート | Resume、See issues | Run now／History（Learn）。トレイ再試行は未確認 | Backup Now、後で自動再試行 |
| 一時停止 | Pause button / Pause Syncing。分数は未確認 | 2 / 8 / 24 hours | 30m / 1h / tomorrow / indefinitely | 未確認 | Remaining=0 でも pause し得る。ユーザー Pause ラベルは未確認 |

---

## 調査2：Microsoft Windows アプリ設計ガイド

### Fluent 2 スペーシング

[Fluent 2 Layout](https://fluent2.microsoft.design/layout)

原文要点:

- 「The base unit is four pixels」
- 「A 4x system reduces confusion while being easy to implement.」
- 2 / 6 / 10 はアイコン余白用で 4px グリッド外
- タッチ: iOS & Web 44×44、Android 48×48
- 近い要素は関連、余白が多い要素は重要に見える。過密は圧倒する

**グローバルランプ（2026-11-20、同頁の表を行ごとに数えた。17トークン）:**

| Token | Value |
| --- | --- |
| sizeNone | 0 |
| size20 | 2 |
| size40 | 4 |
| size60 | 6 |
| size80 | 8 |
| size100 | 10 |
| size120 | 12 |
| size160 | 16 |
| size200 | 20 |
| size240 | 24 |
| size280 | 28 |
| size320 | 32 |
| size360 | 36 |
| size400 | 40 |
| size480 | 48 |
| size520 | 52 |
| size560 | 56 |

ブレイクポイント: small 320–479、medium 480–639、large 640–1023、x-large 1024–1365、xx-large 1366–1919、xxx-large 1920+。

### WinUI レイアウト寸法

**タイトルバー**（[Title bar design](https://learn.microsoft.com/en-us/windows/apps/design/basics/titlebar-design)、Last updated 2024-07-31）

- 標準高さ **32px**
- アイコン 16×16、左から 16px、垂直中央（32px なら上下 8px）
- 検索ボックスまたは person-picture があるとき **48px**
- 空領域はドラッグ。非対話要素の右クリックはシステムメニュー。ダブルクリックは最大化／復元
- フォント: Segoe UI Variable（なければ Segoe UI）、caption

**NavigationView**（[NavigationView](https://learn.microsoft.com/en-us/windows/apps/develop/ui/controls/navigationview)）

- Top: 上位が5以下で同等に重要
- Left: 上位 5–10
- Header 高さ **52 px**。コンテンツ余白: Minimal で **12px**、それ以外 **24px**
- Auto: **1008px 以上** で展開左ペイン、**641–1007px** で LeftCompact、**640px 以下** で LeftMinimal
- 例文は 「changed from the default of 640 to 1007」 とも書く

API 既定:

- [CompactPaneLength](https://learn.microsoft.com/en-us/windows/windows-app-sdk/api/winrt/microsoft.ui.xaml.controls.navigationview.compactpanelength): **48.0 DIP**（`MUXPropertyDefaultValue="48.0"`）
- [OpenPaneLength](https://learn.microsoft.com/en-us/windows/windows-app-sdk/api/winrt/microsoft.ui.xaml.controls.navigationview.openpanelength): **320.0 DIP**
- [CompactModeThresholdWidth](https://learn.microsoft.com/en-us/windows/winui/api/microsoft.ui.xaml.controls.navigationview.compactmodethresholdwidth?view=winui-2.8)（WinUI 2）: **641.0**。「The default is 641 pixels.」

ガイドの 640 と API の 641 は 1px ずれる。両方を併記する。

**コンテンツ余白**（[Content layout and spacing](https://learn.microsoft.com/en-us/windows/apps/design/basics/content-basics)、Last updated 2026-10-14）

- ボタン間 **8epx**
- ボタンとフライアウト **8epx**
- コントロールとヘッダー **8epx**
- コントロールとラベル **12epx**
- コンテンツ領域間 **12epx**
- サーフェスと端のテキスト **16epx**
- 複数行リスト: Body + Caption、アイコン **32epx**
- Expander 内コントロールは **48epx** インデント、コントロールと expander ボタンは **16epx**

WinUI の compact コントロール寸法表（旧 control-sizes）は 2026-11-20 に 404。**未確認**。ボタン最小幅 120px も再取得していないので書かない。

### ProgressBar / ProgressRing

[Guidelines for progress controls](https://learn.microsoft.com/en-us/windows/apps/develop/ui/controls/progress-controls)（Last updated 2026-07-08）

| 状態 | 使い分け |
| --- | --- |
| Determinate ProgressBar | 所要時間が分かる。非モーダル |
| Indeterminate ProgressBar | 所要時間不明。非モーダル。仮想化リストは各行ではなくコレクション先頭に1本 |
| Indeterminate ProgressRing | 操作を止める／入力待ち。キーワード: Refreshing, Signing in..., Connecting... |
| Determinate ProgressRing | 所要時間が分かり、リングが欲しいとき |

ProgressBar キーワード: Loading..., Retrieving, Working...。ユーザーが起していないバックグラウンドはインジケータ不要。完了だけ知らせる選択もある。ProgressRing 最小 **20×20epx**。`IsActive=true` でアニメ。

### InfoBar

[InfoBar](https://learn.microsoft.com/en-us/windows/apps/develop/ui/controls/infobar)（Last updated 2026-02-25）

原文要点:

- 「app-wide status messages」「highly visible yet non-intrusive」
- レイアウト内で他要素を覆わない
- 使う: 接続喪失、自動保存失敗、マイク未接続、サブスク期限
- 使わない: 状態を変えない確認、時間制約の強いアラート、必須でないメッセージ
- 点滅禁止。長寿命ステータス向け
- Severity: Error / Warning / Success（「A long-running and/or background task has completed.」）/ Default
- 色とアイコンだけで意味を伝えない。Title と Message が必要
- バックアップ進行の公式例:

```xml
<InfoBar Title="Backup in progress"
    Message="Your documents are being saved to the cloud"
    IsClosable="False">
    <InfoBar.Content>
        <ProgressBar IsIndeterminate="True" Margin="0,0,0,6" MaxWidth="200"/>
    </InfoBar.Content>
```

取り込み管理の「取り込み中」に直結する公式パターン。

ContentDialog: 操作確認や全操作を止める重大状態。TeachingTip: 一過性の教育。Flyout: 特定 UI の文脈情報。

### アプリ通知（toast）

現行（[Notifications design basics](https://learn.microsoft.com/en-us/windows/apps/develop/notifications/app-notifications/app-notifications-ux-guidance)、Last updated 2026-04-21）

- 「informative and valuable」「shouldn't distract or create more work」
- ボタン、画像、クイック返信、コンテキストメニュー、**progress bars**（ファイルダウンロード等）
- 「Notifications should not be noisy」。抑制して Notification Center へ。Focus Sessions を尊重
- クリックは文脈で起動。バックグラウンド作業（クイック返信）ではアプリを開かない
- 古い通知を Notification Center から消す（既読メール 10 件、同じチャット 10 件のうち1件を開いたら残り9件を消す）

Win32 旧ガイド（Windows 7 向け、現行 UWP へ誘導あり）:

- [Notification Area](https://learn.microsoft.com/en-us/windows/win32/uxguide/winenv-notification): 通知と状態の一時ソース。宣伝に使わない。ユーザーがプロモートするまで隠れ得る。1コンポーネント1アイコン。16/20/24px。コンテキストメニューに Display icon、通知種別、バックグラウンド機能の停止、終了
- [Notifications](https://learn.microsoft.com/en-us/windows/win32/uxguide/mess-notif): 「useful and relevant, but never critical」。Vista 以降 **9 seconds**。非同期のみ。同期結果はダイアログ／バー。IT 向けはログ。無視可能。重要なら progressive escalation（アイコン → 通知 → モーダル）。成功通知は待ち／直前失敗のあとだけ

---

## 調査3：状態の見せ方の UX 研究

### Visibility of system status

Aurora Harley, 2018-06-03, [Visibility of System Status](https://www.nngroup.com/articles/visibility-system-status/)

原文要点:

- 「systems should always keep users informed about what is going on, through appropriate feedback within reasonable time.」
- 状態が分からないと次の一手が決められない（gulf of evaluation）
- 「A lack of information often equates to a lack of control.」
- クリックの色変化、進捗インジケータ。無フィードバックは連打を生む
- バックステージは通常隠す。在庫僅少・在庫切れのようにユーザー行動を変えるときだけ出す
- ウィッシュリストから商品が説明なく消えると信頼を失う。欠品を明示して残す

### 0.1 / 1 / 10 秒

Jakob Nielsen, 1993（2014 追記）, [Response Times: The 3 Important Limits](https://www.nngroup.com/articles/response-times-3-important-limits/)

- **0.1s:** 直接操作に感じる。特別フィードバック不要
- **1.0s:** 思考の流れは保つが遅延は気づく。1秒超はカーソル変更等
- **10s:** 注意を対話に保てる上限。超えたら percent-done と中断手段。戻ったユーザーは再定位が必要

根拠: Miller 1968、Card et al. 1991、Myers 1985（percent-done）。2–10 秒の本格パーセントバーは display inertia に反し得る。未知量なら処理済みの絶対量（データベース名など）。最終手段がスピナー。

### 進捗インジケータ

Katie Sherwin, 2014-10-26, [Progress Indicators Make a Slow System Less Insufferable](https://www.nngroup.com/articles/progress-indicators/)

- 即時フィードバック（ボタン押下状態）
- **約 1.0 秒超** で進捗インジケータ
- **ループ（スピナー）:** 主に **2–10 秒**。1秒未満は distracting。10秒超は「進んでいない」と感じ、固まったか分からない
- **パーセント:** **10 秒以上**。系列処理なら 10 秒未満でも可（「Updating address 3 of 50」）
- 長くかかる処理は中断手段
- 最後の数パーセントで止まるバーは不満を増やす。遅めに始めて後半を速くする（待ち時間の話。調査の進捗バーは逆）
- 概算でよい（「At least a minute」「About 3 minutes remaining」）
- Nebraska-Lincoln の研究: 動き続けるバーあり群は満足が高く、待ち時間は平均約3倍。**この n は記事が再掲しておらず、当調査では再集計していない**

### エラーメッセージ

Tim Neusesser & Evan Sunwall, 2023-05-14, [Error-Message Guidelines](https://www.nngroup.com/articles/error-message-guidelines/)

ヒューリスティック9: Help Users Recognize, Diagnose, and Recover from Errors。

- エラーの近くに出す
- 太字・高コントラスト・赤に加えアイコン。色やアニメだけにしない
- 影響度で設計。軽い問題は toast/banner、進行を止めるものはモーダル
- 空欄からフォーカスが外れただけでエラーにしない
- 人間が読める言葉。404 コードを前面にしない
- 問題を具体的に書き、対処を出す。ユーザーを責めない（invalid / illegal / incorrect を避ける）。頻出エラーにユーモアを使わない
- 入力を保持し、修正候補を出す
- 全面停止のときだけ新規性（Fail Whale 等）

### KPI／数字カード

Page Laubheimer, 2016-11-06, [Cards: UI-Component Definition](https://www.nngroup.com/articles/cards-component/)

カードが向く:

- 異種アイテムのダッシュボード、ソーシャル、集約
- 要約 → 詳細への入口
- 可変の中身（あるカードに画像、別カードに無い）

カードが向かない:

- 検索・特定項目の探索（可変サイズで順位が弱い、スキャンしにくい、画面あたり件数が少ない）
- 比較（視線が行き来する。一貫したリスト／表がよい）
- 同種アイテム（ブログ一覧、商品一覧、同一写真グリッド）

Salesforce ダッシュボードは異種カードの好例として挙げられている。

Aurora Harley, 2019-10-13, [Vanity Metrics](https://www.nngroup.com/articles/vanity-metrics/)

- vanity metric は見栄えするが運用できない（文脈なし、KPI 無関係）
- 単調増加の累計（ユーザー数、DL、PV）は体験の変化を表さない
- 率・比にし、安定した指標の変動を設計変更に結び付ける
- 取り込み管理への含意: 「取り込み済み 12,847」単体は vanity になりやすい。「失敗率」「未処理件数／時間」「最終成功からの経過」が actionable

### アイコンと絵文字

Aurora Harley, 2014-07-27, [Icon Usability](https://www.nngroup.com/articles/icon-usability/)

- 理解は過去経験に依存。標準利用が少ないので **テキストラベルが必要**
- ほぼ普遍なのは home / print / 虫眼鏡程度
- ハートと星は favorites / bookmarks / featured / ratings で競合
- 5秒考えてもアイコンが浮かばない対象はアイコン化しない
- ラベルは常時表示。hover 依存はタッチで失敗する
- 「a word is worth a thousand pictures」（Tognazzini）

Kate Kaplan, 2024-09-20, [The Proliferation and Problem of the ✨ Sparkles ✨ Icon](https://www.nngroup.com/articles/ai-sparkles-icon-problem/)

- スパークルスは「特別」までは共有されるが、中身は曖昧
- 定量（**n=107、NN/g 申告。当調査は再集計していない**）: Favorite/save 16.82%、視覚効果 16.82%、重要／新着 11.22%、報酬 6.54%、ヒント 4.67%（95% CI 併記）
- AI 機能の事実上の記号になっているが、**被験者は誰も「AI」と言わなかった**
- 星と紛らわしい
- ラベル必須。AI が日常化すればスパークルス自体が不要になり得る

アプリクロムの絵文字アイコン専用 NN/g 記事は、2026-11-20 の検索では見つからない。**未確認**。近い一次情報は上記スパークルスと「アイコンにはラベル」である。

---

## 調査4：余白と密度

### Fluent 2（再掲）

4px ベース、トークン名は sizeNone–size560（17個、表を数えた）。公式は黄金比を余白に使わない。

### Windows 寸法（再掲）

タイトルバー 32px（検索／人物で 48px）、NavigationView Compact 48 DIP / Open 320 DIP、header 52px、余白 8/12/16/24 epx。compact コントロール表は 404 のため **未確認**。

### VS Code 実寸（`microsoft/vscode` `main`、2026-11-20 取得）

**Activity Bar** — [`src/vs/workbench/browser/parts/activitybar/activitybarPart.ts`](https://raw.githubusercontent.com/microsoft/vscode/main/src/vs/workbench/browser/parts/activitybar/activitybarPart.ts) L48–L72:

```
static readonly ACTION_HEIGHT = 48;
static readonly COMPACT_ACTION_HEIGHT = 28;
static readonly ACTIVITYBAR_WIDTH = 48;
static readonly COMPACT_ACTIVITYBAR_WIDTH = 36;
static readonly FLOATING_ACTION_HEIGHT = 36;
static readonly FLOATING_ACTIVITYBAR_WIDTH = 36;
static readonly FLOATING_COMPACT_ACTIVITYBAR_WIDTH = 28;
static readonly FLOATING_ACTION_GAP = 8;
static readonly FLOATING_COMPACT_ACTION_GAP = 4;
static readonly ICON_SIZE = 24;
static readonly COMPACT_ICON_SIZE = 16;
```

既定 Activity Bar 幅 **48px**、アイコン行高 **48px**、アイコン **24px**。

**サイドバー** — [`src/vs/workbench/browser/parts/sidebar/sidebarPart.ts`](https://raw.githubusercontent.com/microsoft/vscode/main/src/vs/workbench/browser/parts/sidebar/sidebarPart.ts) L48–L68:

```
readonly minimumWidth: number = 170;
...
return Math.max(width, 300);
```

最小幅 **170**、preferred は viewlet 最適幅と **300** の大きい方。既定の初期ピクセル幅の定数はこのファイルに無い。**未確認（出荷時の初期幅）**。

**ステータスバー** — [`src/vs/workbench/browser/parts/statusbar/media/statusbarpart.css`](https://raw.githubusercontent.com/microsoft/vscode/main/src/vs/workbench/browser/parts/statusbar/media/statusbarpart.css) L6–L11, L57–L59:

```
height: 22px;
font-size: 12px;
...
line-height: 22px;
```

**エクスプローラ行高** — [`src/vs/workbench/contrib/files/browser/views/explorerViewer.ts`](https://raw.githubusercontent.com/microsoft/vscode/main/src/vs/workbench/contrib/files/browser/views/explorerViewer.ts) L75–L81:

```
export class ExplorerDelegate ...
	static readonly ITEM_HEIGHT = 22;
	getHeight(...): number {
		return ExplorerDelegate.ITEM_HEIGHT;
	}
```

失敗ファイル一覧を VS Code 密度にするなら行高 22px、左レール 48px、底の一言バー 22px / 12px がソース根拠になる。

### 黄金比

**公式ガイド:** Fluent 2 Layout、WinUI NavigationView / title bar / content-basics、vscode 上記ソースのいずれも φ を余白や文字サイズに指定しない。**無い。**

**NN/g は「使える参考」であり義務ではない。** Kelley Gordon, 2021-10-31, [The Golden Ratio and User-Interface Design](https://www.nngroup.com/articles/golden-ratio-ui-design/)

- 本文 16px なら見出し 16×1.618≈26px、行送りも同様、という例
- 2カラムを黄金長方形で切る例
- 「Others believe that the golden ratio is no more valid than any other method」
- 引用の Di Dio et al. 2007 は **彫刻** の fMRI であり、UI 余白実験ではない

**Di Dio, Macaluso, Rizzolatti, 2007** [The Golden Beauty](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0001201): 古典・ルネサンス彫刻のカノン比 vs 改変。n=14。観察時に右島などが原作で活性化。美判断では扁桃体。対象は人体彫刻。UI スペーシングへ一般化していない。

**ウェブレイアウトで黄金比が遅かった研究。** van Schaik & Ling, *Computers in Human Behavior* 22(5), 2006, [The effects of graphical display and screen ratio on information retrieval in web pages](https://www.sciencedirect.com/science/article/abs/pii/S074756320400055X)。New Scientist 報道（[Websites break art's 'golden ratio' rule](https://www.newscientist.com/article/1881549-websites-break-arts-golden-ratio-rule/)、2006-04-19 / [別見出し](https://www.newscientist.com/article/1923892-perfectly-proportioned-websites-may-be-the-worst/)、2006-04-21）: 学生 98 人、ナビ:コンテンツ比 5 種。黄金比群は平均 **15.8 秒**、最速群より **3.5 秒** 遅い。van Schaik: 「not only is it not liked in web pages, it is also less efficient in terms of accuracy and speed.」

**製品種別で結果が割れる。** Tractinsky, David, Krupnik, AMCIS 2013, [Exploring the Aesthetic Effects of the Golden Ratio in the Design of Interactive Products](https://aisel.aisnet.org/amcis2013/HumanComputerInteraction/GeneralPresentations/12/): n=91。携帯電話では黄金比仮説を支持、**ウェブページでは支持せず**。

**レビュー。** Green, C. D. (1995). All that glitters. *Perception* 24(8), 937–968. [抄録](https://scispace.com/papers/all-that-glitters-a-review-of-psychological-research-on-the-3s32vx2jsy): 心理効果はあるが「relatively sensitive to careless methodological practices」。

**Fechner 長方形の追試。** Phillips, Norman, Beers (2010). Fechner's aesthetics revisited. *Seeing and Perceiving* 23, 263–271. [PDF](https://www.wku.edu/psychological-sciences/labs/vision_and_haptics/downloads/phillips_norman_aesthetics2010.pdf): より自然な刺激では、被験者は非常に単純か非常に複雑な対象を好み、仮説の黄金長方形と一致しない。

Phillips & Chapparo の「38:62 vs 23:77」ウェブレイアウト比較は、当セッションで本文未取得。**未確認**。

結論: 余白・文字サイズに黄金比を使う公式根拠は無い。ウェブ情報検索では黄金比レイアウトが遅かった査読研究がある。UI 余白の義務比として採用しない。

---

## 調査5：「AI 生成っぽい UI」「vibe-coded UI」批判

### 最大の一次データセット（著者申告、再集計していない）

[JCarterJohnson/vibecoded-design-tells](https://github.com/JCarterJohnson/vibecoded-design-tells) と [DATA_AND_GRAPHS.md](https://raw.githubusercontent.com/JCarterJohnson/vibecoded-design-tells/main/unslop-ai-ui/DATA_AND_GRAPHS.md)

著者の方法: Arctic Shift の公開 Reddit、2020–2026、AI/SaaS 系 47 sub、キーワード・コメント比率。著者申告:

- スキャン投稿 **3,214,533**
- オン・トピック **46,971**（1.46%）
- 正規スレッド 125 本からコメント **3,033**
- 上位 12 tell を別エージェントが検証し 11 確認。mesh/blob/aurora はキーワード誤検出で却下

**ランク表の行数:** 2026-11-20 に markdown 表を数えた。**16行**（umbrella 2 + 具体 9 + 未個別検証 2 + 折り込み 1 + 軽微 1 + REJECTED 1 + bento 1）。

コメント比率（著者、3,033 件分母）:

| Rank | Tell | Comment share |
| --- | --- | --- |
| umbrella | "All looks the same" | 6.1%（投稿 13.1%） |
| umbrella | "Screams AI" / slop | 6.4%（投稿 13.0%） |
| 1 | Default shadcn / Tailwind kit | 2.5% |
| 2 | Purple / violet ("AI purple") | 2.3% |
| 3 | Gradients / gradient hero text | 2.0% |
| 4 | Too many animations / Framer fade-ins | 1.1% |
| 5 | Rounded corners / pill buttons | 0.8% |
| 6 | Dark mode + neon glow | 0.7% |
| 7 | Emoji as icons / sparkles / rockets | 0.5%（投稿側 2.7% で過大） |
| 8 | Generic sans (Inter / Geist) | 0.4% |
| 9 | Symmetric hero + 3 feature cards + CTA | 0.4% |
| — | Bento grid | 0.1%（末位） |
| — | Mesh / blob / aurora | REJECTED |

スキル README の除去対象: 「default shadcn/Tailwind look, AI-purple gradients, gradient hero text, unprompted neon glow, emoji-as-icons, and the centered-hero-plus-three-cards layout」。成長: 2023 年 1.81 / 1万投稿 → 2024 年 277.91（著者表）。

同内容の Reddit 投稿: [r/ClaudeCode, 2026-06-16](https://www.reddit.com/r/ClaudeCode/comments/1u7g0z5/i_scanned_3200000_posts_across_47_ai_and_saas/)。引用例: 「Every Claude/Cursor project defaults to the same shadcn components with identical slate gray cards」「the purple-to-blue gradient is the biggest tell... hero section with gradient text... way too much whitespace」（後者はセット内最高スコア 373 upvotes、著者）。

### Hacker News

[satvikpendem, item 46532369](https://news.ycombinator.com/item?id=46532369)（親スレ [Tailwind 75% layoff, 46527950](https://news.ycombinator.com/item?id=46527950)）。調査日基準で約10か月前 ≈ 2026-01。

原文: 「people can tell it's AI generated now simply due to the gradient, among other design choices LLMs seem to make by default」し、prg.sh の紫グラデーション記事へリンク。prg.sh は 2026-11-20 に **404**。HN コメント自体は一次発言として残る。

### X（Latest、2026-11-20 取得）

- [Aakash Gupta @aakashgupta, 2026-11-17](https://x.com/aakashgupta/status/2122740377274986732): 「There's a specific purple that tells you an app was built by AI before you've read a word.」Adam Wathan の indigo ボタンが「every AI generated UI on earth also being indigo」に繋がった、という話。
- [Suryansh Tiwari @Suryanshti777, 2026-11-16](https://x.com/Suryanshti777/status/2122409103654109348) が引用する [yuj @yyjhao, 2026-11-16](https://x.com/yyjhao/status/2122405576974176370): 「my feed has a new app every day with the same purple gradient」。Epic の vibe-coded ランチャー、Figma Make が Apple Weather を複製した件。
- [@ai_algoit, 2026-11-15](https://x.com/ai_algoit/status/2121966537603248162): unslopovich が 「purple gradients, nested cards and emoji used as icons」を検出。著者は App Store / Play レビュー 1,201,466 件で紫グラデーション言及はゼロ、と主張（**著者申告、再集計していない**）。

### 他の Reddit（2026）

- [r/ClaudeCode, 2026-08-23](https://www.reddit.com/r/ClaudeCode/comments/1vvzqvj/i_finally_figured_out_why_every_aicoded_site/): 「purple gradient hero, rounded cards, glassmorphism everything, "Transform your workflow" headline」。モデルは平均的ランディングに戻る、という主張。
- [r/shadcn, 2026-07-30](https://www.reddit.com/r/shadcn/comments/1vaote8/i_built_a_nextjs_16_shadcnui_admin_dashboard/): ダッシュボード starter への返信「Those cards on mobile view at the top and the icons scream vibe coded」。
- [r/claudeskills, 2026-11-09](https://www.reddit.com/r/claudeskills/comments/1xs352q/i_made_a_claude_code_skill_that_fixes_ai_slop_in/): App Store レビュー 105,027 件をスキャンしたと著者。紫グラデーション言及は **1件で、しかも「作ってほしい」**。低評価で多いのはラグ／クラッシュ 4,326、コントロール移動 1,751、ポップアップ 1,148 等（**キーワード一致、著者。再集計していない**）。社内ツールでは「見た目の AI っぽさ」より操作不能の方が苦情になり得る、という逆証。
- [r/vibecoding, 2026-11-18](https://www.reddit.com/r/vibecoding/comments/1xypjjh/we_built_23_opensource_desktop_apps_w_claude_opus/): 「all-purple gradient minimalist logos」で個別アプリが識別できない、という批判。

### 特徴と一次情報の対応

| 批判される特徴 | 一次情報 |
| --- | --- |
| KPI／数字カード横並び | NN/g: 同種比較には不向き。r/shadcn 2026-07-30「cards... scream vibe coded」。JCarterJohnson #9 hero+3 cards |
| 色付きバッジ | 公式同期アプリは状態をトレイ／オーバーレイで出す。装飾バッジを「AI っぽい」と名指しした件数は当調査で数えていない。**推測:** ラベルなし色バッジは Harley 2014 のアイコン問題と重なる |
| 絵文字アイコン | JCarterJohnson #7。Kaplan 2024 スパークルス。unslopovich が検出対象 |
| 紫／インディゴのグラデーション | JCarterJohnson #2–3。HN satvikpendem。X 2026-11。r/ClaudeCode 2026-06/08 |
| Tailwind/shadcn 既定のまま | JCarterJohnson #1（コメント 2.5%、具体因の首位） |

---

## 取り込み管理アプリへの含意

対象は Windows Electron の社内 RAG 取り込み管理。検索・質問は別アプリ。非エンジニアも使う。要望を画面にするときの根拠だけを書く。

**1. 情報設計は同期クライアントに合わせる。**  
ホームは Drive の Sync status タイル、Dropbox 下部の一言、Backblaze の 「You are backed up as of」＋ Remaining Files に相当する。完了文は Dropbox 原文に近い **「最新の状態です」** で足りる。OneDrive のようにホバーだけ「Up to date」で中身が動いている状態は避ける（[Q&A](https://learn.microsoft.com/en-us/answers/questions/5838820/incorrect-onedrive-status-doesnt-show-activity)）。

**2. 失敗は一覧し、再試行を同じ場所に置く。**  
Drive Error list / Lost and Found、Dropbox See issues、Backblaze Issues。トーストだけで終わらせない。WinUI InfoBar のバックアップ例（ProgressBar 埋め込み、IsClosable=false）を取り込み中に使う。失敗は Error、完了は Success。ActionButton で「失敗を再処理」。

**3. トレイは状態機械にする。**  
Dropbox / OneDrive に合わせ、少なくとも アイドル（最新）／進行／一時停止／エラー／未接続。Win32 ガイドどおり通知は非臨界・無視可能。失敗の詳細はウィンドウ。Focus Session 中は抑制。9秒トーストを連打しない。

**4. 一時停止は期限付き。**  
OneDrive 2/8/24h、Dropbox 30m/1h/明日まで/無期限。無期限だけにしない。File History に Pause 公式が無いことは、バックアップ系でも Pause が必須ではない例。取り込みは帯域を食うので Pause はあった方が Drive/OneDrive/Dropbox に近い。

**5. 進捗は時間で切り替える。**  
Nielsen / Sherwin / WinUI: 1秒未満はボタン状態のみ、2–10秒はスピナー＋「取り込み中…」、10秒以上はパーセントか「ファイル 3/50」。仮想化リストの各行にスピナーを置かない。最後で止まるバーにしない。

**6. 数字カードは「失敗と待ち」に限る。**  
NN/g カードは異種の要約→詳細向き。同種ファイルは 22px 行のリスト（vscode `ExplorerDelegate.ITEM_HEIGHT`）。「総取り込み数」累計は Harley の vanity metric。出すなら失敗件数、未処理、最終成功からの経過、再試行可能件数。横並び KPI は r/shadcn で vibe-coded と名指しされている。

**7. アイコンはラベル付き、絵文字は使わない。**  
Harley 2014、Kaplan 2024、JCarterJohnson #7。フォルダ追加・再処理・設定は文言ボタン。スパークルスで「AI 取り込み」を示さない（このアプリは生成 UI ではなくジョブ管理）。

**8. 余白は 4px ランプ、密度はデスクトップ。**  
Fluent size80/120/160（8/12/16）。タイトル 32px、左ナビ 48px compact、本文 24px。失敗リストは vscode 密度（行 22、ステータス 22/12px）。黄金比で余白や見出しを決めない（公式なし、van Schaik 2006 はウェブで遅い）。

**9. 見た目の既定を避ける。**  
shadcn の slate カード＋ indigo、紫グラデ、ヒーロー＋3カード、Inter/Geist だけ、絵文字、無意味な fade-in は、Reddit コメント比率で「AI サイト」認定される。社内 Windows アプリは Fluent の中立面、システムアクセント、通常の表と InfoBar で足りる。r/claudeskills 2026-11-09 は、実ユーザー苦情が紫グラデよりクラッシュと操作不能であることも示す。見た目掃除より、状態不一致と再試行不能の方が先。

**確認できなかったため設計に使わないもの**

- Drive トレイの回転／塗りつぶし字形一式
- File History のトレイ、Pause、公式の再試行ボタン
- OneDrive 公式アイコン頁の完了一言（Q&A の 「Up to date」 のみ）
- Drive Pause の分数
- WinUI compact コントロール寸法表
- vscode サイドバーの出荷時初期幅
- 黄金比 38:62 レイアウト論文（本文未取得）
- NN/g の絵文字専用ガイドライン
- prg.sh および Medium Laith Aljunaidy（いずれも 404）
