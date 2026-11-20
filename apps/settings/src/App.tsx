import { useCallback, useEffect, useRef, useState } from "react";
import { loadActivity, loadSettings, loadSummary, saveSettings, type Activity, type LocalSettings, type Summary } from "./api";
import { FolderScreen } from "./FolderScreen";
import { Icon } from "./icons";
import { Overview } from "./Overview";
import { SettingsDialog } from "./SettingsDialog";

type Screen = { kind: "overview" } | { kind: "folder"; id: string };

export function App() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [local, setLocal] = useState<LocalSettings | null>(null);
  const [activity, setActivity] = useState<Activity>({ hasMore: false, events: [] });
  const [screen, setScreen] = useState<Screen>({ kind: "overview" });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [adding, setAdding] = useState(false);
  const [path, setPath] = useState("");
  const [error, setError] = useState("");
  const settingsButton = useRef<HTMLButtonElement>(null);

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

  return (
    <div className="app">
      <nav className="side" aria-label="local-rag">
        <div className="brand">local-rag</div>
        <button className={screen.kind === "overview" ? "nav-row is-selected" : "nav-row"} type="button" onClick={() => setScreen({ kind: "overview" })}>
          <Icon name="home" size={18} />
          <span className="t">概要</span>
        </button>
        <div className="cap">取り込むフォルダ</div>
        {(summary?.folders ?? []).map((item) => (
          <button
            key={item.id}
            className={screen.kind === "folder" && screen.id === item.id ? "nav-row is-selected" : "nav-row"}
            type="button"
            onClick={() => setScreen({ kind: "folder", id: item.id })}
          >
            <Icon name="folder" size={18} />
            <span className="t">{item.name}</span>
            {item.failed > 0 ? (
              <span className="meta num"><Icon name="err" size={12} />{item.failed}件失敗</span>
            ) : (
              <span className="meta num">{item.total}件</span>
            )}
          </button>
        ))}
        <button className="nav-row" type="button" onClick={() => setAdding((open) => !open)}>
          <Icon name="plus" size={18} />
          <span className="t">フォルダを追加</span>
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
            <button className="quiet" type="submit">追加</button>
          </form>
        ) : null}
        <div className="spacer" />
        <button ref={settingsButton} className="nav-row" type="button" onClick={() => setSettingsOpen(true)}>
          <Icon name="gear" size={18} />
          <span className="t">設定</span>
        </button>
      </nav>
      <main className="main">
        {error ? <p className="error-line">{error}</p> : null}
        {summary ? <ScreenBody screen={screen} summary={summary} folder={folder} local={local} activity={activity.events} showAll={showAll} onShowAll={() => setShowAll(true)} onReload={refresh} /> : null}
      </main>
      {settingsOpen ? (
        <SettingsDialog
          onClose={() => {
            setSettingsOpen(false);
            settingsButton.current?.focus();
          }}
        />
      ) : null}
    </div>
  );
}

function ScreenBody({
  screen,
  summary,
  folder,
  local,
  activity,
  showAll,
  onShowAll,
  onReload,
}: {
  screen: Screen;
  summary: Summary;
  folder: Summary["folders"][number] | null;
  local: LocalSettings | null;
  activity: Activity["events"];
  showAll: boolean;
  onShowAll: () => void;
  onReload: () => Promise<void>;
}) {
  switch (screen.kind) {
    case "overview":
      return <Overview summary={summary} activity={activity} showAll={showAll} onShowAll={onShowAll} onReload={onReload} />;
    case "folder":
      return folder ? <FolderScreen folder={folder} local={local} onReload={onReload} /> : null;
    default: {
      const never: never = screen;
      return never;
    }
  }
}
