# Notion の見た目の値（調査日 2026-11-20 JST）

区分: 【実測】= 私が 2026-11-20 に Playwright（Chrome）で公開ページを開き getComputedStyle で読んだ値 / 【書き出しCSS】= Notion の HTML 書き出しに付く CSS（第三者の gist に転載） / 【第三者採取】= ds.dotui.org が Notion を採取・レビューした値（私は再測定していない） / 【第三者テーマ】= Obsidian の Notion 風テーマの変数（Notion 公式ではない） / 【未確認】

## 実測（https://notion.notion.site/Notion-Official-83715d7703ee4b8699b5e659a4712dd8 、1440×900）
- 文字の並び: `ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI Variable Display", "Segoe UI", Helvetica, "Apple Color Emoji", "Noto Sans Arabic", "Noto Sans Hebrew", Arial, sans-serif, "Segoe UI Emoji", "Segoe UI Symbol"`（日本語専用のフォント指定はない）
- ページタイトル: 40px / 48px、700、色 rgb(44, 44, 43)、左右 padding 8px
- 本文: 16px / 24px、400、色 rgb(44, 44, 43)
- 本文の列: 幅 720px、1440px 幅の画面で x=360（中央寄せ）
- 区切り線（divider ブロック）: 高さ 1px、背景 rgba(28, 19, 1, 0.11)、幅 704px
- 注: 読み込み直後（スクリプト前）の文字色は rgb(55, 53, 47)。2回目以降のアクセスは Cloudflare の確認画面（"Just a moment..."）で止まり、サイドバー・表・コールアウトは測れなかった。

## 書き出しCSS（https://gist.github.com/rajatkumar/af87e1cbeaeafc499576da4069db9bf0 、旧世代の値）
- 本文色 rgb(55,53,47)、本文の最大幅 900px
- ページタイトル 2.5rem/700、h1 1.875rem、h2 1.5rem、h3 1.25rem、見出しは 600・line-height 1.2・letter-spacing -0.01em
- 区切り線 1px solid rgba(55,53,47,0.09)
- 表: 罫線 rgba(55,53,47,0.09)、セル padding 0.25em 0.5em、line-height 1.5、見出しセル色 rgba(55,53,47,0.6)、データベース（collection）の文字 0.875rem
- コールアウト: radius 3px、padding 1rem（別版 16px 16px 16px 12px、https://github.com/asnunes/notion-page-to-html/commit/c791a2a9c0a8799fbdb7c4ec985cddb8862a3400 ）
- 灰色の文字 rgb(155,154,151)、赤 rgb(224,62,62)、灰色の背景 rgb(235,236,237)

## 第三者採取（https://ds.dotui.org/systems/notion ）
- 色: 文字 #2c2c2b（= 実測の rgb(44,44,43) と一致）、弱い文字 #7d7a75、サイドバー #f9f8f7、縁取り rgba(42,28,0,0.07)（≒#f0efed）を box-shadow の 1px リングで描く、青 #2783de（ボタン）/ #2383e2（フォーカス）
- 文字: 本文 16/24、操作部品 14px（ラベル・主ボタン 500、静かなもの 400）、補足 12px
- 角丸: ボタン・メニュー行 6px、カード・メニュー 10px、ダイアログ 12px
- 余白: 2px 刻み、6・8px が多く次が 12px。操作部品の高さ 28px、小 24px、ビューのタブ 32px
- 影: カード 4px 12px の淡い影、メニュー 20px 24px、ダイアログ 24px 48px
- ボタン: 28px、角丸 6px、ホバーまで塗りなし
- メニュー: 白、角丸 10px、行 28px、最初の行は 5% の塗りと 2px の青いリング
- 表の行の罫線: 7% の 1px
- サイドバーの行（公開ページの浮くサイドバー）: 30px、文字 16px、アイコン 20px
- 状態プロパティは色付きのピル（本件では使わない）

## 第三者テーマ（https://community.obsidian.md/themes/notion-style ）
- ホバー rgba(55,53,47,0.06)、選択 rgba(55,53,47,0.12)、弱い文字 #787774、さらに弱い文字 #9b9a97、縁 rgba(55,53,47,0.16)、サイドバー #fafaf8

## Notion 公式ヘルプ（https://www.notion.com/help/account-settings ）
- 設定はサイドバーのワークスペース名から開き、左の項目（{名前}、Preferences など）を選ぶ。右は見出し（Language & Time、Privacy）で分けた行に、ドロップダウンやトグルを右に置く。
- 外観は「Use system setting / Light / Dark」の3択。

## 未確認
- アプリ内サイドバーの既定幅（240px と広く言われるが未測定）、文字サイズ（14px と推定）、ホバー・選択の色
- データベースの表ビューの行の高さ、見出し行の値
- 設定モーダルの寸法、背景の暗さ
- トグル（スイッチ）の寸法と色
- アプリ内コールアウトの背景色
