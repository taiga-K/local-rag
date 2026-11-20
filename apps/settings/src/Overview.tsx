import { useEffect, useRef, useState } from "react";
import {
  loadRecords,
  reprocessRecord,
  retryFailed,
  setPause,
  type FolderCount,
  type RecordRow,
  type Summary,
} from "./api";
import { clock } from "./format";
import { Icon } from "./icons";
import { failureLine, resultLabel } from "./view";

type Failed = RecordRow & { kbId: string; kbName: string };
type Phase = "working" | "done";

const PAUSE_ITEMS = [
  { kind: "30m", label: "30分" },
  { kind: "1h", label: "1時間" },
  { kind: "tomorrow", label: "明日まで" },
  { kind: "resume", label: "再開するまで" },
] as const;

export function Overview({
  summary,
  activity,
  onReload,
  onShowAll,
  showAll,
}: {
  summary: Summary;
  activity: { at: string | null; folder: string; text: string; name?: string; status?: string }[];
  onReload: () => Promise<void>;
  onShowAll: () => void;
  showAll: boolean;
}) {
  const [menu, setMenu] = useState(false);
  const [failed, setFailed] = useState<Failed[]>([]);
  const [held, setHeld] = useState<Record<string, Failed>>({});
  const [phase, setPhase] = useState<Record<string, Phase>>({});
  const [note, setNote] = useState("");
  const [fileShown, setFileShown] = useState(summary.current?.recordName ?? "");
  const [fileDim, setFileDim] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const lastSwap = useRef(0);
  const importing = !summary.pause.active && (summary.active > 0 || summary.queued > 0);
  const ratio = summary.total === 0 ? 0 : summary.done / summary.total;

  const foldersRef = useRef(summary.folders);
  foldersRef.current = summary.folders;
  const failedKey = summary.folders.map((folder) => `${folder.id}:${folder.failed}`).join("|");
  useEffect(() => {
    let stop = false;
    let busy = false;
    const run = () => {
      if (busy || stop) {
        return;
      }
      busy = true;
      void Promise.all(
        foldersRef.current
          .filter((folder) => folder.failed > 0)
          .map(async (folder) => {
            const records = await loadRecords(folder.id, "FAILED");
            return records
              .filter((row) => row.indexingStatus === "FAILED")
              .map((row) => ({ ...row, kbId: folder.id, kbName: folder.name }));
          }),
      ).then((groups) => {
        busy = false;
        if (!stop) {
          setFailed(groups.flat());
        }
      }).catch((error: unknown) => {
        busy = false;
        if (!stop) {
          setNote(error instanceof Error ? error.message : "失敗したファイルを読めません");
        }
      });
    };
    run();
    const timer = window.setInterval(run, 5000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [failedKey]);

  useEffect(() => {
    const next = summary.current?.recordName ?? "";
    if (!next) {
      setFileShown("");
      setFileDim(false);
      return;
    }
    const now = Date.now();
    if (next === fileShown || now - lastSwap.current < 1000) {
      return;
    }
    lastSwap.current = now;
    setFileDim(true);
    const timer = window.setTimeout(() => {
      setFileShown(next);
      setFileDim(false);
    }, 150);
    return () => window.clearTimeout(timer);
  }, [summary.current, fileShown]);

  useEffect(() => {
    setPhase((current) => {
      let changed = false;
      const next = { ...current };
      for (const id of Object.keys(current)) {
        if (current[id] === "working" && !failed.some((row) => row.recordId === id)) {
          next[id] = "done";
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [failed]);

  const visible = [
    ...failed.filter((row) => phase[row.recordId] === undefined),
    ...Object.keys(phase).map((id) => held[id] ?? failed.find((row) => row.recordId === id)).filter((row): row is Failed => row !== undefined),
  ];
  async function pause(kind: string | null) {
    setMenu(false);
    menuButton.current?.focus();
    const until = kind === "tomorrow" ? nextLocalMidnight() : null;
    try {
      await setPause(kind, until);
      await onReload();
    } catch (error: unknown) {
      setNote(error instanceof Error ? error.message : "一時停止を保存できませんでした");
    }
  }

  async function retry(row: Failed) {
    setHeld((current) => ({ ...current, [row.recordId]: row }));
    setPhase((current) => ({ ...current, [row.recordId]: "working" }));
    setNote("");
    try {
      await reprocessRecord(row.kbId, row.externalRecordId);
      await onReload();
    } catch (error: unknown) {
      setPhase((current) => {
        const next = { ...current };
        delete next[row.recordId];
        return next;
      });
      setNote(error instanceof Error ? error.message : "再試行に失敗しました");
    }
  }

  return (
    <div className="col">
      <h1 className="page-title" data-measure="page-title">概要</h1>
      <div className="status" role="status" aria-live="polite">
        <div className="state-line">
          <div>
            <span className="state-name" data-measure="state-name">{stateName(summary, importing)}</span>
            {summary.total > 0 ? (
              <span className="state-count num" data-measure="state-count">
                {importing || summary.pause.active ? `${summary.total}件中${summary.done}件` : `${summary.total}件`}
              </span>
            ) : null}
          </div>
        {importing || summary.pause.active ? (
          <div className="menu-wrap">
            <button
              ref={menuButton}
              className="quiet"
              type="button"
              aria-haspopup="menu"
              aria-expanded={summary.pause.active ? undefined : menu}
              onClick={() => {
                if (summary.pause.active) {
                  void pause(null);
                  return;
                }
                setMenu((open) => !open);
              }}
            >
              {summary.pause.active ? <Icon name="check" /> : <Icon name="pause" />}
              {summary.pause.active ? "再開" : "一時停止"}
              {summary.pause.active ? null : <Icon name="chev" />}
            </button>
            <div className="menu" data-open={menu ? "true" : "false"} role="menu">
              {summary.pause.active ? (
                <button type="button" onClick={() => void pause(null)}>再開する</button>
              ) : (
                PAUSE_ITEMS.map((item) => (
                  <span key={item.kind}>
                    {item.kind === "resume" ? <hr /> : null}
                    <button type="button" role="menuitem" onClick={() => void pause(item.kind)}>{item.label}</button>
                  </span>
                ))
              )}
            </div>
          </div>
        ) : (
          <button className="quiet" type="button" onClick={() => void onReload()}>今すぐ確認</button>
        )}
        </div>
      </div>
      {importing || summary.pause.active ? (
        <div
          className={summary.pause.active ? "bar is-paused" : "bar"}
          data-measure="progress"
          role="progressbar"
          aria-valuemin={0}
          aria-valuenow={summary.done}
          aria-valuemax={summary.total}
          aria-valuetext={`${summary.done} / ${summary.total}`}
        >
          <i className="progress__fill" style={{ transform: `scaleX(${ratio})` }} />
        </div>
      ) : null}
      {importing && fileShown ? (
        <div className={fileDim ? "current-file is-swapping" : "current-file"}>
          読み込み中: {fileShown}
        </div>
      ) : null}
      {visible.length > 0 ? (
        <section className="section" id="failed-files">
          <div className="sec-head">
            <div className="sec-title">
              <h2 data-measure="section-title">取り込めなかったファイル</h2>
              <span className="count num">{visible.length}件</span>
            </div>
            <button
              className="quiet"
              type="button"
              onClick={() => {
                for (const row of visible) {
                  setHeld((current) => ({ ...current, [row.recordId]: row }));
                  setPhase((current) => ({ ...current, [row.recordId]: "working" }));
                }
                const ids = visible.map((row) => row.recordId);
                void retryFailed().then(() => onReload()).catch((error: unknown) => {
                  setPhase((current) => {
                    const next = { ...current };
                    for (const id of ids) {
                      delete next[id];
                    }
                    return next;
                  });
                  setHeld((current) => {
                    const next = { ...current };
                    for (const id of ids) {
                      delete next[id];
                    }
                    return next;
                  });
                  setNote(error instanceof Error ? error.message : "再試行に失敗しました");
                });
              }}
            >
              すべて再試行
            </button>
          </div>
          <div className="rule" />
          {visible.map((row) => (
            <FailRow
              key={row.recordId}
              row={row}
              phase={phase[row.recordId]}
              onDone={() => {
                setPhase((current) => {
                  const next = { ...current };
                  delete next[row.recordId];
                  return next;
                });
                setHeld((current) => {
                  const next = { ...current };
                  delete next[row.recordId];
                  return next;
                });
              }}
              onRetry={() => void retry(row)}
            />
          ))}
        </section>
      ) : null}
      <section className="section">
        <div className="sec-head">
          <h2>最近の変更</h2>
          {showAll ? null : <button className="quiet" type="button" onClick={onShowAll}>すべての履歴</button>}
        </div>
        <div className="rows">
          {activity.map((event, index) => (
            <div className="log" key={`${event.at}-${index}`}>
              <time className="num" dateTime={event.at ?? undefined}>{clock(event.at)}</time>
              <span className="name">{event.name || event.text}</span>
              <span className={event.status === "FAILED" ? "result is-failed" : "result"}>
                {event.status === "FAILED" ? <Icon name="err" size={12} /> : null}
                {event.status ? resultLabel(event.status) : ""}
              </span>
              <span className="folder">{event.folder}</span>
            </div>
          ))}
        </div>
      </section>
      {note ? <p className="error-line">{note}</p> : null}
    </div>
  );
}

function FailRow({
  row,
  phase,
  onRetry,
  onDone,
}: {
  row: Failed;
  phase: Phase | undefined;
  onRetry: () => void;
  onDone: () => void;
}) {
  const sentence = phase === "done"
    ? "再試行を受け付けました"
    : failureLine(row.failureClassified, row.failureMessage);
  return (
    <div
      className="fail-row"
      data-state={phase === "done" ? "done" : "open"}
      aria-busy={phase === "working"}
      onTransitionEnd={(event) => {
        if (phase !== "done" || event.target !== event.currentTarget) {
          return;
        }
        if (event.propertyName === "opacity" || event.propertyName === "grid-template-rows") {
          onDone();
        }
      }}
    >
      <div className="fail-row__inner">
        <span className="err-icon">
          {phase === "working" ? <span className="spinner" /> : phase === "done" ? <Icon name="check" /> : <Icon name="err" />}
        </span>
        <div>
          <div className="fail-name">{row.recordName}</div>
          <div className="fail-why" data-measure="fail-why">{sentence}</div>
          <div className="fail-path">{row.kbName}</div>
        </div>
        <button className="quiet" type="button" disabled={phase === "working"} onClick={onRetry}>
          {phase === "working" ? "再試行中…" : "再試行"}
        </button>
      </div>
    </div>
  );
}

function stateName(summary: Summary, importing: boolean): string {
  if (summary.total === 0 && !summary.pause.active) {
    return "取り込むファイルはありません";
  }
  if (summary.pause.active) {
    return "一時停止中";
  }
  if (importing) {
    return "取り込み中";
  }
  return "すべて取り込み済み";
}

function nextLocalMidnight(): string {
  const next = new Date();
  next.setDate(next.getDate() + 1);
  next.setHours(0, 0, 0, 0);
  return next.toISOString();
}

export type { FolderCount };
