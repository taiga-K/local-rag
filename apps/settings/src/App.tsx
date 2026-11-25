import { useCallback, useEffect, useState } from "react";
import { loadActivity, loadSettings, loadSummary, saveSettings, type Activity, type LocalSettings, type Summary } from "./api";
import { folderBridge, folderPathKey } from "./bridge";
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
  const [pickingFolder, setPickingFolder] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");

  const refresh = useCallback(async () => {
    const [nextSummary, nextLocal, nextActivity] = await Promise.all([
      loadSummary(),
      loadSettings(),
      loadActivity(showAll ? 50 : 8),
    ]);
    setSummary(nextSummary);
    setLocal(nextLocal);
    setActivity(nextActivity);
    setLoadError("");
  }, [showAll]);

  useEffect(() => {
    let stop = false;
    const run = () => {
      void refresh().catch((cause: unknown) => {
        if (!stop) {
          setLoadError(cause instanceof Error ? cause.message : "設定を読めません");
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

  async function addFolder() {
    if (pickingFolder) {
      return;
    }
    const bridge = folderBridge();
    if (!bridge) {
      setActionError("フォルダ選択はデスクトップアプリで使えます");
      return;
    }
    if (!local) {
      return;
    }
    setPickingFolder(true);
    setActionError("");
    try {
      const picked = await bridge.pickFolder();
      if (picked.canceled) {
        return;
      }
      const selected = picked.path ?? "";
      if (!picked.ok || !selected) {
        setActionError(picked.error || "フォルダを選択できませんでした");
        return;
      }
      const current = await loadSettings();
      const selectedKey = folderPathKey(selected);
      if (current.folders.some((folder) => folderPathKey(folder) === selectedKey)) {
        setActionError("そのフォルダはすでに追加されています");
        return;
      }
      const saved = await saveSettings({ ...current, folders: [...current.folders, selected] });
      setLocal(saved);
      await refresh();
    } catch (cause: unknown) {
      setActionError(cause instanceof Error ? cause.message : "フォルダを追加できませんでした");
    } finally {
      setPickingFolder(false);
    }
  }

  const importing = summary != null && !summary.pause.active && (summary.active > 0 || summary.queued > 0);
  const error = actionError || loadError;
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
          <button className="nav add" type="button" disabled={pickingFolder || !local} onClick={() => void addFolder()}>
            {Glyph.plus}<span className="name">フォルダを追加</span>
          </button>
        </div>
        <button className={screen.kind === "settings" ? "nav on" : "nav"} type="button" onClick={() => setScreen({ kind: "settings" })}>
          {Glyph.gear}<span className="name">設定</span>
        </button>
      </aside>
      <main className="main">
        {error ? <p className="error-line">{error}</p> : null}
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
            onAddFolder={() => void addFolder()}
          />
        ) : null}
      </main>
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
