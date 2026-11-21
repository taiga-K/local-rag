import { useEffect, useRef, useState, type RefObject } from "react";
import {
  loadRecords,
  reprocessRecord,
  retryFailed,
  setPause,
  type Activity,
  type FolderCount,
  type LocalSettings,
  type RecordRow,
  type Summary,
} from "./api";
import { longStamp, stamp } from "./format";
import { Glyph } from "./glyphs";
import { failureLine, remainingOf } from "./view";

type Failed = RecordRow & { kbId: string; kbName: string };

const PAUSE_ITEMS = [
  { kind: "30m", label: "30分" },
  { kind: "1h", label: "1時間" },
  { kind: "tomorrow", label: "明日まで" },
  { kind: "resume", label: "再開するまで" },
] as const;

export function Overview({
  summary,
  local,
  activity,
  showAll,
  onShowAll,
  onReload,
  onAddFolder,
}: {
  summary: Summary;
  local: LocalSettings | null;
  activity: Activity["events"];
  showAll: boolean;
  onShowAll: () => void;
  onReload: () => Promise<void>;
  onAddFolder: () => void;
}) {
  const importing = !summary.pause.active && (summary.active > 0 || summary.queued > 0);
  const [menu, setMenu] = useState(false);
  const [failed, setFailed] = useState<Failed[]>([]);
  const [note, setNote] = useState("");
  const menuButton = useRef<HTMLButtonElement>(null);
  const ratio = summary.total === 0 ? 0 : summary.done / summary.total;
  const indexed = summary.folders.reduce((sum, folder) => sum + folder.completed + (folder.empty ?? 0), 0);
  const paths = new Map((local?.folders ?? []).map((folder) => [folder.split(/[/\\]/).filter(Boolean).pop() ?? folder, folder]));

  useEffect(() => {
    let stop = false;
    const load = () => {
      void Promise.all(summary.folders.filter((folder) => folder.failed > 0).map(async (folder) => {
        const rows = await loadRecords(folder.id, "FAILED");
        return rows.map((row) => ({ ...row, kbId: folder.id, kbName: folder.name }));
      })).then((groups) => {
        if (!stop) {
          setFailed(groups.flat());
        }
      }).catch(() => {
        if (!stop) {
          setNote("失敗したファイルを読めません");
        }
      });
    };
    load();
    const timer = window.setInterval(load, 5000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [summary.folders]);

  async function pause(kind: string | null) {
    setMenu(false);
    const until = kind === "tomorrow" ? nextLocalMidnight() : null;
    try {
      await setPause(kind, until);
      await onReload();
    } catch (error: unknown) {
      setNote(error instanceof Error ? error.message : "一時停止を保存できませんでした");
    }
  }

  const shown = showAll ? activity : activity.slice(0, 8);
  return (
    <div className="col">
      <h1>概要</h1>
      <StatusLine
        summary={summary}
        importing={importing}
        indexed={indexed}
        ratio={ratio}
        menu={menu}
        menuButton={menuButton}
        onToggle={() => setMenu((open) => !open)}
        onPause={pause}
        onReload={onReload}
      />
      {failed.length > 0 ? (
        <section>
          <div className="sec-head">
            <h2>取り込めなかったファイル<span className="n">{failed.length}件</span></h2>
            <button className="btn sm" type="button" onClick={() => void retryFailed().then(() => onReload())}>すべて再試行</button>
          </div>
          <div className="rows">
            {failed.map((row) => (
              <div className="r fail" key={row.recordId}>
                <span className="ic bad">{Glyph.err}</span>
                <div className="grow">
                  <div>{row.recordName}</div>
                  <div className="msg">{failureLine(row.failureClassified, row.failureMessage, row.recordName)}</div>
                </div>
                <button
                  className="btn sm"
                  type="button"
                  onClick={() => void reprocessRecord(row.kbId, row.externalRecordId).then(() => onReload())}
                >
                  再試行
                </button>
              </div>
            ))}
          </div>
        </section>
      ) : null}
      <section>
        <div className="sec-head">
          <h2>取り込むフォルダ</h2>
          <button className="btn sm" type="button" onClick={onAddFolder}>{Glyph.plus}フォルダを追加</button>
        </div>
        <div className="rows">
          {summary.folders.map((folder) => (
            <div className="r" key={folder.id}>
              <span className="ic">{Glyph.folder}</span>
              <span style={{ flex: "none" }}>{folder.name}</span>
              <span className="grow sub">{paths.get(folder.name) ?? folder.name}</span>
              <CountBits folder={folder} importing={importing || summary.pause.active} />
            </div>
          ))}
        </div>
      </section>
      <section>
        <div className="sec-head">
          <h2>最近の変更</h2>
          {showAll ? null : <button className="link" type="button" onClick={onShowAll}>すべての履歴</button>}
        </div>
        <div className="rows recent">
          {shown.map((event, index) => (
            <div className="r" key={`${event.at}-${index}`}>
              <span className="time">{stamp(null, event.at)}</span>
              <span className="kind">{event.kind ?? ""}</span>
              <span className="fn">{event.name || event.text}</span>
              <span className="fd">{event.folder}</span>
            </div>
          ))}
        </div>
      </section>
      {note ? <p className="error-line">{note}</p> : null}
    </div>
  );
}

function StatusLine({
  summary,
  importing,
  indexed,
  ratio,
  menu,
  menuButton,
  onToggle,
  onPause,
  onReload,
}: {
  summary: Summary;
  importing: boolean;
  indexed: number;
  ratio: number;
  menu: boolean;
  menuButton: RefObject<HTMLButtonElement | null>;
  onToggle: () => void;
  onPause: (kind: string | null) => void;
  onReload: () => Promise<void>;
}) {
  if (importing || summary.pause.active) {
    return (
      <div className="status">
        <div className="line">
          <span className={summary.pause.active ? "ic" : "ic spin"}>{Glyph.sync}</span>
          <span className="title">{summary.pause.active ? "一時停止中" : "取り込み中"}</span>
          <span className="meta pair">
            <span>残り{summary.queued + summary.active}件</span>
            {summary.etaText ? <span>{summary.etaText}</span> : null}
          </span>
          <div className="menu-wrap">
            <button ref={menuButton} className="btn" type="button" onClick={() => (summary.pause.active ? onPause(null) : onToggle())}>
              {Glyph.pause}{summary.pause.active ? "再開" : "一時停止"}{summary.pause.active ? null : Glyph.down}
            </button>
            {menu ? (
              <div className="menu pause-menu" role="menu">
                {PAUSE_ITEMS.map((item) => (
                  <button key={item.kind} type="button" role="menuitem" onClick={() => onPause(item.kind)}>{item.label}</button>
                ))}
              </div>
            ) : null}
          </div>
        </div>
        <div className="bar" role="progressbar" aria-valuenow={summary.done} aria-valuemax={summary.total}>
          <i style={{ width: `${Math.round(ratio * 100)}%` }} />
        </div>
        {summary.current ? <div className="now">読み込み中: {summary.current.recordName}</div> : null}
      </div>
    );
  }
  if (summary.failed > 0) {
    return (
      <div className="status">
        <div className="line">
          <span className="ic bad">{Glyph.err}</span>
          <span className="title">一部を取り込めませんでした</span>
          <span className="meta pair">
            <span>取り込み済み {indexed}件</span>
            {summary.latestAt ? <span>最終確認 {longStamp(summary.latestAt)}</span> : null}
          </span>
          <div className="menu-wrap">
            <button className="btn" type="button" onClick={() => void onReload()}>今すぐ確認</button>
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="status">
      <div className="line">
        <span className="ic ok">{Glyph.ok}</span>
        <span className="title">取り込み完了</span>
        <span className="meta pair">
          <span>取り込み済み {indexed}件</span>
          {summary.latestAt ? <span>最終確認 {longStamp(summary.latestAt)}</span> : null}
        </span>
        <div className="menu-wrap">
          <button className="btn" type="button" onClick={() => void onReload()}>今すぐ確認</button>
        </div>
      </div>
    </div>
  );
}

function CountBits({ folder, importing }: { folder: FolderCount; importing: boolean }) {
  const remaining = remainingOf(folder);
  const indexed = folder.completed + (folder.empty ?? 0);
  const bits: { label: string; value: number; bad?: boolean }[] = [];
  if (importing || remaining > 0 || folder.failed > 0) {
    if (indexed > 0) {
      bits.push({ label: "取り込み済み", value: indexed });
    }
    if (remaining > 0) {
      bits.push({ label: "残り", value: remaining });
    }
    if (folder.failed > 0) {
      bits.push({ label: "失敗", value: folder.failed, bad: true });
    }
  } else {
    bits.push({ label: "取り込み済み", value: indexed });
  }
  return (
    <span className="cnt">
      {bits.map((bit) => (
        <span key={bit.label}>{bit.label} <b className={bit.bad ? "bad" : undefined}>{bit.value}</b></span>
      ))}
    </span>
  );
}

function nextLocalMidnight(): string {
  const next = new Date();
  next.setDate(next.getDate() + 1);
  next.setHours(0, 0, 0, 0);
  return next.toISOString();
}
