import { useCallback, useEffect, useRef, useState } from "react";
import { loadActivity, loadSettings, loadSummary, saveSettings, type Activity, type LocalSettings, type Summary } from "./api";
import { ToastStack, type ToastItem } from "./ErrorToast";
import { FolderScreen } from "./FolderScreen";
import { Glyph } from "./glyphs";
import { Overview } from "./Overview";
import { SettingsScreen } from "./SettingsDialog";

type Screen = { kind: "overview" } | { kind: "folder"; id: string } | { kind: "settings" };

export function App() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [local, setLocal] = useState<LocalSettings | null>(null);
  const [activity, setActivity] = useState<Activity>({ hasMore: false, events: [] });
  const [screen, setScreen] = useState<Screen>({ kind: "overview" });
  const [showAll, setShowAll] = useState(false);
  const [adding, setAdding] = useState(false);
  const [path, setPath] = useState("");
  const [error, setError] = useState("");
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextToast = useRef(1);
  const previousFailed = useRef<number | null>(null);

  const notifyError = useCallback((message: string) => {
    const id = nextToast.current++;
    setToasts((items) => [...items.slice(-2), { id, message }]);
  }, []);

  const closeToast = useCallback((id: number) => {
    setToasts((items) => items.filter((item) => item.id !== id));
  }, []);

  const refresh = useCallback(async () => {
    const [nextSummary, nextLocal, nextActivity] = await Promise.all([
      loadSummary(),
      loadSettings(),
      loadActivity(showAll ? 50 : 8),
    ]);
    setSummary(nextSummary);
    setLocal(nextLocal);
    setActivity(nextActivity);
    setError("");
  }, [showAll]);

  useEffect(() => {
    let stop = false;
    const run = () => {
      void refresh().catch((cause: unknown) => {
        if (!stop) {
          setError(cause instanceof Error ? cause.message : "設定を読めません");
        }
      });
    };
    run();
    const timer = window.setInterval(run, 1000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [refresh]);

  const folder = summary?.folders.find((item) => item.id === (screen.kind === "folder" ? screen.id : "")) ?? null;
  useEffect(() => {
    if (screen.kind === "folder" && summary && folder === null) {
      setScreen({ kind: "overview" });
    }
  }, [screen, summary, folder]);

  useEffect(() => {
    if (!summary) {
      return;
    }
    if (previousFailed.current !== null && summary.failed > previousFailed.current) {
      const added = summary.failed - previousFailed.current;
      notifyError(`${added}件のファイルを取り込めませんでした`);
    }
    previousFailed.current = summary.failed;
  }, [summary, notifyError]);

  useEffect(() => {
    if (error) {
      notifyError(error);
    }
  }, [error, notifyError]);

  const importing = summary != null && !summary.pause.active && (summary.active > 0 || summary.queued > 0);
  return (
    <div className="app">
      <aside className="side">
        <div className="side-scroll">
          <div className="brand">local-rag</div>
          <button className={screen.kind === "overview" ? "nav on" : "nav"} type="button" onClick={() => setScreen({ kind: "overview" })}>
            {Glyph.home}<span className="name">概要</span>
          </button>
          <div className="label">取り込むフォルダ</div>
          {(summary?.folders ?? []).map((item) => (
            <button
              key={item.id}
              className={screen.kind === "folder" && screen.id === item.id ? "nav on" : "nav"}
              type="button"
              onClick={() => setScreen({ kind: "folder", id: item.id })}
            >
              {Glyph.folder}
              <span className="name">{item.name}</span>
              {importing && item.active + item.queued > 0 ? <span className="mark spin">{Glyph.syncSmall}</span> : null}
              {!importing && item.failed > 0 ? <span className="mark bad">{Glyph.errSmall}</span> : null}
            </button>
          ))}
          <button className="nav add" type="button" onClick={() => setAdding((open) => !open)}>
            {Glyph.plus}<span className="name">フォルダを追加</span>
          </button>
          {adding ? (
            <form
              className="add-row"
              onSubmit={(event) => {
                event.preventDefault();
                if (!local || !path.trim()) {
                  return;
                }
                const next = { ...local, folders: [...local.folders, path.trim()] };
                void saveSettings(next).then((saved) => {
                  setLocal(saved);
                  setPath("");
                  setAdding(false);
                }).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : "保存に失敗しました"));
              }}
            >
              <input aria-label="追加するフォルダ" value={path} onChange={(event) => setPath(event.target.value)} />
              <button className="btn sm" type="submit">追加</button>
            </form>
          ) : null}
        </div>
        <button className={screen.kind === "settings" ? "nav on" : "nav"} type="button" onClick={() => setScreen({ kind: "settings" })}>
          {Glyph.gear}<span className="name">設定</span>
        </button>
      </aside>
      <main className="main">
        {summary ? (
          <Body
            screen={screen}
            summary={summary}
            folder={folder}
            local={local}
            activity={activity}
            showAll={showAll}
            onShowAll={() => setShowAll(true)}
            onReload={refresh}
            onAddFolder={() => setAdding(true)}
          />
        ) : null}
      </main>
      <ToastStack toasts={toasts} onClose={closeToast} />
    </div>
  );
}

function Body({
  screen,
  summary,
  folder,
  local,
  activity,
  showAll,
  onShowAll,
  onReload,
  onAddFolder,
}: {
  screen: Screen;
  summary: Summary;
  folder: Summary["folders"][number] | null;
  local: LocalSettings | null;
  activity: Activity;
  showAll: boolean;
  onShowAll: () => void;
  onReload: () => Promise<void>;
  onAddFolder: () => void;
}) {
  switch (screen.kind) {
    case "overview":
      return (
        <Overview
          summary={summary}
          local={local}
          activity={activity.events}
          showAll={showAll}
          onShowAll={onShowAll}
          onReload={onReload}
          onAddFolder={onAddFolder}
        />
      );
    case "folder":
      return folder ? <FolderScreen key={folder.id} folder={folder} local={local} onReload={onReload} /> : null;
    case "settings":
      return <SettingsScreen />;
    default: {
      const never: never = screen;
      return never;
    }
  }
}
