I = {
 'home':'<path d="M2.5 7.5 8 3l5.5 4.5V13a.5.5 0 0 1-.5.5H10v-4H6v4H3a.5.5 0 0 1-.5-.5z"/>',
 'folder':'<path d="M1.5 4a1 1 0 0 1 1-1h3.6l1.5 1.5h5.9a1 1 0 0 1 1 1V12a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1z"/>',
 'plus':'<path d="M8 3v10M3 8h10"/>',
 'gear':'<circle cx="8" cy="8" r="2"/><path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4"/>',
 'err':'<circle cx="8" cy="8" r="6"/><path d="M8 4.75v3.75M8 10.75v.5"/>',
 'pause':'<path d="M6 4v8M10 4v8"/>',
 'search':'<circle cx="7" cy="7" r="4"/><path d="m10 10 3.5 3.5"/>',
 'back':'<path d="M10 3 5 8l5 5"/>',
 'info':'<circle cx="8" cy="8" r="6"/><path d="M8 7.25v4M8 4.75v.5"/>',
 'chev':'<path d="m4 6 4 4 4-4"/>',
 'check':'<circle cx="8" cy="8" r="6"/><path d="m5.5 8 1.75 1.75L10.5 6.5"/>',
}
def ic(n,cls='i'): return f'<svg class="{cls}" viewBox="0 0 16 16">{I[n]}</svg>'
TB = '''<div class="titlebar"><div class="name">local-rag</div><div class="wc">
<span><svg viewBox="0 0 10 10"><path d="M0 5h10"/></svg></span>
<span><svg viewBox="0 0 10 10"><rect x=".5" y=".5" width="9" height="9"/></svg></span>
<span><svg viewBox="0 0 10 10"><path d="M0 0l10 10M10 0 0 10"/></svg></span></div></div>'''
FOLDERS=[('議事録','1','214'),('仕様書','',' 96'),('見積・請求','2','128'),('社内規程','','42')]
def side(sel, fails=True):
    h=f'<div class="nav {"on" if sel=="概要" else ""}">{ic("home")}<span class="t">概要</span></div>'
    h+='<div class="cap">取り込むフォルダ</div>'
    for n,e,c in FOLDERS:
        meta = f'<span class="meta err">{ic("err")}{e}件失敗</span>' if (e and fails) else f'<span class="meta num">{c.strip()}件</span>'
        h+=f'<div class="nav {"on" if sel==n else ""}">{ic("folder")}<span class="t">{n}</span>{meta}</div>'
    h+=f'<div class="nav add">{ic("plus")}<span class="t">フォルダを追加</span></div>'
    h+=f'<div class="spacer"></div><div class="foot"><div class="nav">{ic("gear")}<span class="t">設定</span></div></div>'
    return f'<div class="side">{h}</div>'
def page(name, sidebar, main):
    open(f'{name}.html','w').write(f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><link rel="stylesheet" href="base.css"></head><body>{TB}<div class="app">{sidebar}<div class="main">{main}</div></div></body></html>')

# ---------- overview ----------
def status(running=True, menu=False):
    if running:
        m = '' if not menu else '''<div class="menu" style="right:0;top:40px">
<div class="on">30分</div><div>1時間</div><div>明日まで</div><hr><div>再開するまで</div></div>'''
        return f'''<div class="status"><div class="body">
<h1>取り込み中です<span class="num" style="font-weight:400;color:var(--fg2);margin-left:16px">132 / 480 件　残り約6分</span></h1>
</div><div style="position:relative"><span class="btn">{ic("pause")}一時停止{ic("chev")}</span>{m}</div></div>
<div class="bar"><i style="width:27.5%"></i></div>
<div class="caption" style="margin-top:8px">いま読んでいるファイル：2026-11 営業会議 議事録.docx（議事録）</div>'''
    return f'''<div class="status"><div class="body"><h1>すべて取り込み済みです</h1>
<div class="sub" style="margin-top:4px">480件　11月20日 23:10 時点</div></div>
<div><span class="btn">今すぐ確認</span></div></div>'''
FAILS=[('2026年度 予算申請書.pdf','パスワード付きPDFのため読めません。パスワードを外して保存し直してください。',r'C:\Users\taiga\Documents\見積・請求\2026'),
('取引先一覧_最新.xlsx','ファイルが別のアプリで開かれています。閉じてから再試行してください。',r'C:\Users\taiga\Documents\見積・請求'),
('定例メモ 10月.one','対応していない形式です（.one）。WordかPDF で書き出すと取り込めます。',r'C:\Users\taiga\Documents\議事録\2026-10')]
def fails():
    rows=''.join(f'''<div class="fail"><span class="ic">{ic("err")}</span><div class="b"><div class="fn">{f}</div>
<div class="why">{w}</div><div class="p caption">{p}</div></div><div class="act"><span class="link">再試行</span></div></div>''' for f,w,p in FAILS)
    return f'''<div class="section"><div class="sechead"><h2>取り込めなかったファイル　<span class="num">3</span>件</h2><span class="link">すべて再試行</span></div>{rows}</div>'''
LOG=[('23:08','「2026-11 営業会議 議事録.docx」を追加しました','議事録'),
('22:51','「API仕様 v2.docx」の更新を反映しました','仕様書'),
('22:47','「旧 見積テンプレート.xlsx」を索引から削除しました','見積・請求'),
('21:30','フォルダ「社内規程」を追加しました　42件','社内規程'),
('18:02','「2026-11 定例議事録.pdf」を追加しました','議事録')]
def log():
    rows=''.join(f'<div class="log"><span class="tm num">{t}</span><span class="tx">{x}</span><span class="caption" style="padding-top:2px">{f}</span></div>' for t,x,f in LOG)
    return f'<div class="section"><div class="sechead"><h2>最近の変更</h2><span class="link muted">すべての履歴</span></div>{rows}</div>'
page('overview', side('概要'), f'<div class="col">{status()}{fails()}{log()}</div>')
page('overview-pause', side('概要'), f'<div class="col">{status(menu=True)}{fails()}{log()}</div>')
page('overview-idle', side('概要', False), f'<div class="col">{status(False)}{log()}</div>')

# ---------- folder ----------
FILES=[('2026-11 営業会議 議事録.docx','11/20 23:08','取り込み中'),
('定例メモ 10月.one','10/31 17:40','ERR'),
('2026-11 定例議事録.pdf','11/20 18:02','取り込み済み'),
('2026-10 定例議事録.pdf','10/31 17:40','取り込み済み'),
('2026-10 営業会議 議事録.docx','10/28 19:12','取り込み済み'),
('経営会議 議事録 2026年10月期.pdf','10/24 10:05','取り込み済み'),
('採用面談メモ_中途_10月.docx','10/22 15:31','取り込み済み'),
('2026-09 定例議事録.pdf','09/30 17:55','取り込み済み'),
('プロジェクト振り返り_第3四半期.md','09/29 11:20','取り込み済み'),
('2026-09 営業会議 議事録.docx','09/26 19:03','取り込み済み'),
('取締役会 議事録 2026年9月.pdf','09/19 13:40','取り込み済み'),
('2026-08 定例議事録.pdf','08/29 17:48','取り込み済み'),
('顧客打合せ_A社_0827.docx','08/27 16:10','取り込み済み'),
('2026-08 営業会議 議事録.docx','08/25 18:56','取り込み済み')]
def frow(n,d,s):
    if s=='ERR':
        return f'''<tr class="e1"><td class="n">{n}</td><td class="d num">{d}</td><td class="s"><span class="e">{ic("err")}失敗</span></td></tr>
<tr class="e2"><td colspan="3"><span class="sub">対応していない形式です（.one）。WordかPDFで書き出すと取り込めます。</span><span class="link" style="margin-left:16px">再試行</span></td></tr>'''
    return f'<tr><td class="n">{n}</td><td class="d num">{d}</td><td class="s">{s}</td></tr>'
folder=f'''<div class="col">
<div style="display:flex;align-items:flex-start;gap:24px"><div style="flex:1"><h1>議事録</h1>
<div class="caption mono" style="margin-top:4px;white-space:nowrap">C:\\Users\\taiga\\Documents\\議事録　下の階層を含む</div></div>
<div style="display:flex;gap:8px"><span class="btn">エクスプローラーで開く</span><span class="btn">取り込みから外す</span></div></div>
<p style="margin-top:24px">214件のうち212件を取り込み済み、1件は取り込み中、1件は取り込めませんでした。</p>
<div style="display:flex;gap:16px;align-items:center;margin-top:24px">
<div class="input" style="width:320px">{ic("search")}ファイル名で絞り込む</div>
<label style="display:flex;gap:8px;align-items:center;color:var(--fg2)"><span style="width:16px;height:16px;border:1px solid #616161;border-radius:2px;display:inline-block"></span>取り込めなかったものだけ</label></div>
<table style="margin-top:16px"><tr><th>名前</th><th>更新日時</th><th>状態</th></tr>{"".join(frow(*f) for f in FILES)}</table>
</div>'''
page('folder', side('議事録'), folder)

# ---------- settings ----------
CATS=['取り込み','索引','検索結果','表示']
sside='<div class="side">'+f'<div class="nav" style="color:var(--fg2)">{ic("back")}<span class="t">設定を閉じる</span></div><div class="cap">設定</div>'
sside+=''.join(f'<div class="nav {"on" if c=="索引" else ""}"><span class="t">{c}</span></div>' for c in CATS)+'</div>'
settings=f'''<div class="col">
<h1>設定</h1>
<div class="section" style="margin-top:32px"><div class="sechead"><h2>索引</h2></div>
<div class="row" style="display:block"><div style="display:flex;gap:24px"><div class="l"><div>埋め込みモデル</div><div class="caption">取り込み済みのデータがあるあいだは変更できません。モデルが変わると、これまでの索引では検索できなくなるためです。</div></div>
<div class="c"><span class="select">ruri-v3-130m（軽量）{ic("chev")}</span></div></div>
<div class="notice"><span style="color:var(--accent);padding-top:2px">{ic("info")}</span><div><div>変更すると<span class="num">480</span>件すべてを取り込み直します。目安は約40分です。</div>
<div class="acts"><span class="btn primary">変更する</span><span class="btn">キャンセル</span></div></div></div></div>
<div class="row"><div class="l"><div>計算に使う装置</div><div class="caption">GPUがあると取り込みが速くなります。</div></div><div class="c"><span class="select" style="min-width:120px">CPU{ic("chev")}</span></div></div>
</div>
<div class="section"><div class="sechead"><h2>検索結果</h2></div>
<div class="row"><div class="l"><div>類似度のしきい値</div><div class="caption" style="color:var(--fg2)">オンにすると、質問との類似度がこの値より低い文書を検索結果から外します。結果が0件になることがあります。</div></div>
<div class="c"><span class="field-dis num">0.50</span><span class="toggle"></span><span class="sub" style="white-space:nowrap">オフ</span></div></div>
</div></div>'''
page('settings', sside, settings)
