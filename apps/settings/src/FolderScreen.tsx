import { useEffect, useState } from "react";
import { detachKb, loadRecords, reprocessRecord, type FolderCount, type LocalSettings, type RecordRow } from "./api";
import { configuredFolder, folderBridge } from "./bridge";
import { stamp } from "./format";
import { Icon } from "./icons";
import { failureLine, folderSentence, statusLabel, visibleRecords } from "./view";

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
    void loadRecords(folder.id).then((rows) => {
      if (!stop) {
        setRecords(rows);
      }
    }).catch((error: unknown) => {
      if (!stop) {
        setNote(error instanceof Error ? error.message : "ファイルを読めません");
      }
    });
    return () => {
      stop = true;
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
          <div className="path">
            {local?.includeSubfolders ? "下の階層を含む" : "そのフォルダだけ"}
            {local && local.folders.length > 0 ? `　${local.folders.join("、")}` : ""}
          </div>
        </div>
        <div style={{ display: "flex", gap: 4 }}>
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
      <p className="sub" style={{ marginTop: 16 }}>{folderSentence(folder)}</p>
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
            <FileRows key={row.recordId} row={row} folder={folder} onRetried={() => void loadRecords(folder.id).then(setRecords)} />
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

function FileRows({ row, folder, onRetried }: { row: RecordRow; folder: FolderCount; onRetried: () => void }) {
  const failed = row.indexingStatus === "FAILED";
  return (
    <>
      <tr>
        <td>{row.recordName}</td>
        <td className="num">{stamp(row.sourceModifiedMs, row.updatedAt)}</td>
        <td>
          {failed ? (
            <span className="fail-state"><Icon name="err" size={14} />失敗</span>
          ) : (
            <span style={{ color: "var(--text-2)" }}>{statusLabel(row.indexingStatus)}</span>
          )}
        </td>
      </tr>
      {failed ? (
        <tr className="fail-extra">
          <td colSpan={3}>
            <span>{failureLine(row.failureClassified, row.failureMessage)}</span>
            <button className="retry-link" type="button" onClick={() => void reprocessRecord(folder.id, row.externalRecordId).then(onRetried)}>
              再試行
            </button>
          </td>
        </tr>
      ) : null}
    </>
  );
}
