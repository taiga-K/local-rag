import { useEffect, useState } from "react";
import { detachKb, loadRecords, reprocessRecord, type FolderCount, type LocalSettings, type RecordRow } from "./api";
import { configuredFolder, folderBridge } from "./bridge";
import { stamp } from "./format";
import { Icon } from "./icons";
import { failureLine, folderCountItems, statusLabel, visibleRecords } from "./view";

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
  const [query, setQuery] = useState("");
  const [failedOnly, setFailedOnly] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [note, setNote] = useState("");

  useEffect(() => {
    let stop = false;
    let busy = false;
    const run = () => {
      if (busy || stop) {
        return;
      }
      busy = true;
      void loadRecords(folder.id).then((rows) => {
        busy = false;
        if (!stop) {
          setRecords(rows);
        }
      }).catch((error: unknown) => {
        busy = false;
        if (!stop) {
          setNote(error instanceof Error ? error.message : "ファイルを読めません");
        }
      });
    };
    run();
    const timer = window.setInterval(run, 5000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [folder.id]);

  const shown = visibleRecords(records, query, failedOnly);
  const openable = local ? configuredFolder(local.folders, folder.name) : null;
  const bridge = folderBridge();
  return (
    <div className="col">
      <div className="page-head">
        <div>
          <h1 className="page-title">{folder.name}</h1>
          {local && local.folders.length > 0 ? <div className="path">{local.folders.join("、")}</div> : null}
          <div className="path-sub">{local?.includeSubfolders ? "下の階層も取り込む" : "そのフォルダだけ"}</div>
        </div>
        <div className="page-actions">
          {openable && bridge ? (
            <button
              className="quiet"
              type="button"
              onClick={() => {
                void bridge.openPath(openable).then((result) => {
                  if (!result.ok) {
                    setNote(result.error || "フォルダを開けませんでした");
                  }
                });
              }}
            >
              エクスプローラーで開く
            </button>
          ) : null}
          <button className="quiet" type="button" onClick={() => setConfirm(true)}>取り込みから外す</button>
        </div>
      </div>
      {folder.total === 0 ? (
        <p className="count-line">ファイルはありません</p>
      ) : (
        <div className="count-line num">
          {folderCountItems(folder).map((item) => item.key === "failed" ? (
            <button key={item.key} className="quiet" type="button" onClick={() => setFailedOnly(true)}>
              {item.label} {item.count}
            </button>
          ) : (
            <span key={item.key}>{item.label} {item.count}</span>
          ))}
        </div>
      )}
      <div className="tools">
        <label className="search">
          <Icon name="search" />
          <input value={query} placeholder="ファイル名で絞り込む" onChange={(event) => setQuery(event.target.value)} />
        </label>
        <button className={failedOnly ? "quiet is-on" : "quiet"} type="button" onClick={() => setFailedOnly((on) => !on)}>
          取り込めなかったものだけ
        </button>
      </div>
      <table className="files">
        <thead>
          <tr>
            <th>名前</th>
            <th className="num">更新日時</th>
            <th>状態</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((row) => (
            <FileRow
              key={row.recordId}
              row={row}
              folder={folder}
              onRetried={() => void loadRecords(folder.id).then(setRecords)}
              onError={setNote}
            />
          ))}
        </tbody>
      </table>
      {note ? <p className="error-line">{note}</p> : null}
      {confirm ? (
        <div className="confirm" role="dialog" aria-modal="true">
          <p>{folder.name}の {folder.total} 件を索引から外します。ファイル自体は消えません。</p>
          <div className="acts">
            <button
              className="quiet"
              type="button"
              onClick={() => {
                void detachKb(folder.id).then(() => onReload()).catch((error: unknown) => {
                  setNote(error instanceof Error ? error.message : "外せませんでした");
                });
                setConfirm(false);
              }}
            >
              外す
            </button>
            <button className="quiet" type="button" onClick={() => setConfirm(false)}>キャンセル</button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function FileRow({
  row,
  folder,
  onRetried,
  onError,
}: {
  row: RecordRow;
  folder: FolderCount;
  onRetried: () => void;
  onError: (message: string) => void;
}) {
  const failed = row.indexingStatus === "FAILED";
  return (
    <tr className={failed ? "is-failed" : undefined}>
      <td>
        <div>{row.recordName}</div>
        {failed ? <div className="file-why">{failureLine(row.failureClassified, row.failureMessage)}</div> : null}
      </td>
      <td className="num">{stamp(row.sourceModifiedMs, row.updatedAt)}</td>
      <td>
        {failed ? (
          <span className="fail-state">
            <Icon name="err" size={12} />
            失敗
            <button
              className="retry-link"
              type="button"
              onClick={() => {
                void reprocessRecord(folder.id, row.externalRecordId).then(onRetried).catch((error: unknown) => {
                  onError(error instanceof Error ? error.message : "再試行に失敗しました");
                });
              }}
            >
              再試行
            </button>
          </span>
        ) : (
          <span style={{ color: "var(--text-2)" }}>{statusLabel(row.indexingStatus)}</span>
        )}
      </td>
    </tr>
  );
}
