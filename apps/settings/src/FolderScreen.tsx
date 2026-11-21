import { useEffect, useState } from "react";
import {
  detachKb,
  loadRecords,
  reprocessRecord,
  retryFailed,
  type FolderCount,
  type LocalSettings,
  type RecordRow,
} from "./api";
import { folderBridge, configuredFolder } from "./bridge";
import { stamp } from "./format";
import { Glyph } from "./glyphs";
import { failureLine, failureShort, remainingOf } from "./view";

type Filter = "all" | "done" | "left" | "failed";

export function FolderScreen({
  folder,
  local,
  onReload,
}: {
  folder: FolderCount;
  local: LocalSettings | null;
  onReload: () => Promise<void>;
}) {
  const [records, setRecords] = useState<RecordRow[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [more, setMore] = useState(false);
  const [menu, setMenu] = useState(false);
  const [note, setNote] = useState("");
  const path = local ? configuredFolder(local.folders, folder.name) : null;
  const indexed = folder.completed + (folder.empty ?? 0);
  const remaining = remainingOf(folder);

  useEffect(() => {
    let stop = false;
    const load = () => {
      void loadRecords(folder.id).then((rows) => {
        if (!stop) {
          setRecords(rows);
        }
      }).catch(() => {
        if (!stop) {
          setNote("ファイルを読めません");
        }
      });
    };
    load();
    const timer = window.setInterval(load, 5000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [folder.id]);

  const needle = query.trim().toLowerCase();
  const matches = (row: RecordRow) => !needle || row.recordName.toLowerCase().includes(needle);
  const byTime = (leftRow: RecordRow, rightRow: RecordRow) => (rightRow.updatedAt ?? "").localeCompare(leftRow.updatedAt ?? "");
  const failed = records.filter((row) => row.indexingStatus === "FAILED" && matches(row)).sort(byTime);
  const left = records.filter((row) => (row.indexingStatus === "QUEUED" || row.indexingStatus === "IN_PROGRESS") && matches(row)).sort((leftRow, rightRow) => {
    if (leftRow.indexingStatus === rightRow.indexingStatus) {
      return byTime(leftRow, rightRow);
    }
    return leftRow.indexingStatus === "IN_PROGRESS" ? -1 : 1;
  });
  const done = records.filter((row) => (row.indexingStatus === "COMPLETED" || row.indexingStatus === "EMPTY") && matches(row)).sort(byTime);
  const shownLeft = more || filter === "left" ? left : left.slice(0, 4);
  const hiddenLeft = left.length - shownLeft.length;

  return (
    <div className="col">
      <div className="head">
        <h1>{folder.name}</h1>
        <div className="actions">
          {path && folderBridge() ? (
            <button
              className="btn"
              type="button"
              onClick={() => {
                const bridge = folderBridge();
                if (!bridge) {
                  return;
                }
                void bridge.openPath(path).then((result) => {
                  if (!result.ok) {
                    setNote(result.error || "フォルダを開けませんでした");
                  }
                });
              }}
            >
              {Glyph.ext}エクスプローラーで開く
            </button>
          ) : null}
          <div className="menu-wrap">
            <button className="btn icon" type="button" title="その他" onClick={() => setMenu((open) => !open)}>{Glyph.more}</button>
            {menu ? (
              <div className="menu" role="menu">
                <button
                  className="mi"
                  type="button"
                  onClick={() => {
                    setMenu(false);
                    void detachKb(folder.id).then(() => onReload()).catch((error: unknown) => {
                      setNote(error instanceof Error ? error.message : "外せませんでした");
                    });
                  }}
                >
                  取り込みから外す
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </div>
      <div className="path">
        {path ?? folder.name}
        {local?.includeSubfolders ? "（下の階層も含む）" : "（そのフォルダだけ）"}
      </div>
      <div className="toolbar">
        <div className="tabs">
          <Tab id="all" label="すべて" count={folder.total} filter={filter} onFilter={setFilter} />
          <Tab id="done" label="取り込み済み" count={indexed} filter={filter} onFilter={setFilter} />
          <Tab id="left" label="残り" count={remaining} filter={filter} onFilter={setFilter} />
          <Tab id="failed" label="失敗" count={folder.failed} filter={filter} onFilter={setFilter} />
        </div>
        <label className="search">
          {Glyph.search}
          <input value={query} placeholder="ファイル名で検索" onChange={(event) => setQuery(event.target.value)} />
        </label>
      </div>
      <div className="list">
        <div className="lh"><span /><span>名前</span><span>更新日時</span><span>状態</span></div>
        {filter === "all" || filter === "failed" ? (
          failed.length > 0 ? (
            <>
              <div className="grp">
                <span className="ic bad">{Glyph.errSmall}</span>
                <span className="gt">失敗</span>
                <span className="gn">{failed.length}</span>
                <button
                  className="btn"
                  type="button"
                  onClick={() => {
                    void retryFailed().then(() => loadRecords(folder.id).then(setRecords)).then(() => onReload());
                  }}
                >
                  すべて再試行
                </button>
              </div>
              {failed.map((row) => (
                <FileLine key={row.recordId} row={row} folder={folder} failed onChanged={() => void loadRecords(folder.id).then(setRecords)} />
              ))}
            </>
          ) : null
        ) : null}
        {filter === "all" || filter === "left" ? (
          left.length > 0 ? (
            <>
              <div className="grp">
                <span className="ic">{Glyph.syncSmall}</span>
                <span className="gt">残り</span>
                <span className="gn">{left.length}</span>
              </div>
              {shownLeft.map((row) => <FileLine key={row.recordId} row={row} folder={folder} onChanged={() => undefined} />)}
              {hiddenLeft > 0 ? (
                <div className="more"><span /><button className="link" type="button" onClick={() => setMore(true)}>残りの{hiddenLeft}件を表示</button></div>
              ) : null}
            </>
          ) : null
        ) : null}
        {filter === "all" || filter === "done" ? (
          done.length > 0 ? (
            <>
              <div className="grp">
                <span className="ic ok">{Glyph.okSmall}</span>
                <span className="gt">取り込み済み</span>
                <span className="gn">{done.length}</span>
              </div>
              {done.map((row) => <FileLine key={row.recordId} row={row} folder={folder} onChanged={() => undefined} />)}
            </>
          ) : null
        ) : null}
      </div>
      {note ? <p className="error-line">{note}</p> : null}
    </div>
  );
}

function Tab({
  id,
  label,
  count,
  filter,
  onFilter,
}: {
  id: Filter;
  label: string;
  count: number;
  filter: Filter;
  onFilter: (next: Filter) => void;
}) {
  return (
    <button className={filter === id ? "tab on" : "tab"} type="button" onClick={() => onFilter(id)}>
      {label}<span className="c">{count}</span>
    </button>
  );
}

function FileLine({
  row,
  folder,
  failed = false,
  onChanged,
}: {
  row: RecordRow;
  folder: FolderCount;
  failed?: boolean;
  onChanged: () => void;
}) {
  const working = row.indexingStatus === "IN_PROGRESS";
  return (
    <div className="file">
      <div className="li">
        <span className={failed ? "ic bad" : "ic"}>
          {failed ? Glyph.err : working ? <span className="spin" style={{ display: "flex" }}>{Glyph.syncSmall}</span> : Glyph.doc}
        </span>
        <span className="nm">{row.recordName}</span>
        <span className="dt">{stamp(row.sourceModifiedMs, row.updatedAt)}</span>
        <span className="why">
          {failed
            ? failureShort(row.failureClassified, row.failureMessage, row.recordName)
            : working
              ? "読み込み中"
              : ""}
        </span>
        {failed ? (
          <button
            className="btn sm rt"
            type="button"
            onClick={() => void reprocessRecord(folder.id, row.externalRecordId).then(onChanged)}
          >
            再試行
          </button>
        ) : null}
      </div>
      {failed ? <div className="tip">{failureLine(row.failureClassified, row.failureMessage, row.recordName)}</div> : null}
    </div>
  );
}
