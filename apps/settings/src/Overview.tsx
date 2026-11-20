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
import { clock, longStamp } from "./format";
import { Icon } from "./icons";
import { failureLine } from "./view";

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
  activity: { at: string | null; folder: string; text: string }[];
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
  const idle = !summary.pause.active && !importing;
  const ratio = summary.total === 0 ? 0 : summary.done / summary.total;

  useEffect(() => {
    let stop = false;
    void Promise.all(
      summary.folders
        .filter((folder) => folder.failed > 0)
        .map(async (folder) => {
          const records = await loadRecords(folder.id);
          return records
            .filter((row) => row.indexingStatus === "FAILED")
            .map((row) => ({ ...row, kbId: folder.id, kbName: folder.name }));
        }),
    ).then((groups) => {
      if (!stop) {
        setFailed(groups.flat());
      }
    }).catch((error: unknown) => {
      if (!stop) {
        setNote(error instanceof Error ? error.message : "失敗したファイルを読めません");
      }
    });
    return () => {
      stop = true;
    };
  }, [summary]);

  useEffect(() => {
    const next = summary.current?.recordName ?? "";
    const now = Date.now();
    if (!next || next === fileShown || now - lastSwap.current < 1000) {
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
  const headline = headlineOf(summary);
  async function pause(kind: string | null) {
    setMenu(false);
    menuButton.current?.focus();
    const until = kind === "tomorrow" ? nextLocalMidnight() : null;
    await setPause(kind, until);
    await onReload();
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
      <div className="status" role="status" aria-live="polite">
        <div>
          <h1 className="page-title">
            {headline.title}
            {headline.rest ? <span className="rest num">{`　${headline.rest}`}</span> : null}
          </h1>
          {idle && summary.total > 0 ? <div className="sub num">{headline.caption}</div> : null}
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
      {importing ? (
        <>
          <div
            className="bar"
            role="progressbar"
            aria-valuemin={0}
            aria-valuenow={summary.done}
            aria-valuemax={summary.total}
            aria-valuetext={`${summary.done} / ${summary.total} 件`}
          >
            <i className="progress__fill" style={{ transform: `scaleX(${ratio})` }} />
          </div>
          {fileShown ? (
            <div className={fileDim ? "current-file is-swapping" : "current-file"}>
              いま読んでいるファイル：{fileShown}（{summary.current?.kbName}）
            </div>
          ) : null}
        </>
      ) : null}
      {visible.length > 0 ? (
        <section className="section">
          <div className="sec-head">
            <h2>取り込めなかったファイル <span className="count num">{visible.length}件</span></h2>
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
              <span>{event.text}</span>
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
          <div className="fail-why">{sentence}</div>
          <div className="fail-path">{row.kbName}</div>
        </div>
        <button className="quiet" type="button" disabled={phase === "working"} onClick={onRetry}>
          {phase === "working" ? "再試行中…" : "再試行"}
        </button>
      </div>
    </div>
  );
}

function headlineOf(summary: Summary): { title: string; rest: string; caption: string } {
  const counts = `${summary.done} / ${summary.total} 件`;
  if (summary.total === 0 && !summary.pause.active) {
    return { title: "取り込むファイルはありません", rest: "", caption: "" };
  }
  if (summary.pause.active) {
    const when = summary.pause.until ? `${longStamp(summary.pause.until)} に再開` : "再開するまで停止しています";
    return { title: "一時停止中です", rest: `${counts}　${when}`, caption: "" };
  }
  if (summary.active > 0 || summary.queued > 0) {
    return { title: "取り込み中です", rest: counts, caption: "" };
  }
  if (summary.failed > 0 || (summary.held ?? 0) > 0) {
    return { title: "取り込みが終わっていません", rest: counts, caption: "" };
  }
  return {
    title: "すべて取り込み済みです",
    rest: "",
    caption: `${summary.total}件${summary.latestAt ? `　${longStamp(summary.latestAt)} 時点` : ""}`,
  };
}

function nextLocalMidnight(): string {
  const next = new Date();
  next.setDate(next.getDate() + 1);
  next.setHours(0, 0, 0, 0);
  return next.toISOString();
}

export type { FolderCount };
