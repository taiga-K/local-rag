import { app, BrowserWindow, dialog, ipcMain, shell } from "electron";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import {
  cloneMarkerNames,
  composeUpArgs,
  detectDocker,
  ensureEnv,
  HEALTH_URL,
  missingCloneFiles,
  pollHealth,
  readSavedClone,
  spawnExec,
  volumesToRemove,
  writeSavedClone,
} from "./stack.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const API_BASE = process.env.KBINDEX_API ?? "http://127.0.0.1:43123";

function insideFolder(root: string, target: string): boolean {
  let base: string;
  let full: string;
  try {
    base = fs.realpathSync(root);
    full = fs.realpathSync(target);
  } catch {
    return false;
  }
  const relative = path.relative(base, full);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

ipcMain.handle("localrag:pick-folder", async (event) => {
  const options = {
    title: "取り込むフォルダを選択",
    buttonLabel: "追加",
    properties: ["openDirectory", "createDirectory"] as Array<"openDirectory" | "createDirectory">,
  };
  const win = BrowserWindow.fromWebContents(event.sender);
  const result = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
  const folder = result.filePaths[0] ?? null;
  return { ok: !result.canceled && folder !== null, canceled: result.canceled, path: folder, error: null };
});

ipcMain.handle("localrag:open-path", async (_event, raw: unknown) => {
  if (typeof raw !== "string" || !raw.trim()) {
    return { ok: false, error: "path" };
  }
  let folders: string[] = [];
  try {
    const response = await fetch(`${API_BASE}/api/v1/settings/local`);
    const body = (await response.json()) as { folders?: unknown };
    folders = Array.isArray(body.folders) ? body.folders.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return { ok: false, error: "settings" };
  }
  const target = path.resolve(raw);
  if (!folders.some((folder) => insideFolder(folder, target))) {
    return { ok: false, error: "outside" };
  }
  let directory = false;
  try {
    directory = fs.statSync(target).isDirectory();
  } catch {
    directory = false;
  }
  if (!directory) {
    return { ok: false, error: "directory" };
  }
  const opened = await shell.openPath(target);
  return { ok: opened === "", error: opened || null };
});

function createWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 700,
    webPreferences: {
      contextIsolation: true,
      sandbox: true,
      preload: path.join(here, "preload.cjs"),
    },
  });
  return win;
}

function loadApp(win: BrowserWindow): void {
  const devUrl = process.env.ELECTRON_RENDERER_URL;
  if (devUrl) {
    void win.loadURL(devUrl);
    return;
  }
  void win.loadURL(pathToFileURL(path.join(here, "../dist/index.html")).href);
}

function showStatus(win: BrowserWindow, text: string): void {
  const body = text.replace(/[&<>]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[char] ?? char);
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>kbindex</title></head><body style="font-family:sans-serif;padding:40px;background:#111;color:#eee"><h1>kbindex</h1><pre style="white-space:pre-wrap">${body}</pre></body></html>`;
  void win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
}

async function pickClone(win: BrowserWindow | null): Promise<string | null> {
  const options = {
    title: "kbindex のフォルダを選択",
    buttonLabel: "このフォルダを使う",
    properties: ["openDirectory"] as Array<"openDirectory">,
  };
  const result = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
  return result.canceled ? null : result.filePaths[0] ?? null;
}

async function removeStack(deletePostgres: boolean): Promise<void> {
  const launch = await detectDocker(spawnExec, process.platform);
  if ("error" in launch) {
    return;
  }
  const listed = await spawnExec(launch.command, launch.mode === "wsl"
    ? ["-e", "docker", "volume", "ls", "-q", "--filter", "label=com.docker.compose.project=kbindex"]
    : ["volume", "ls", "-q", "--filter", "label=com.docker.compose.project=kbindex"]);
  const names = listed.stdout.split(/\r?\n/).map((line: string) => line.trim()).filter(Boolean);
  const containers = await spawnExec(launch.command, launch.mode === "wsl"
    ? ["-e", "docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=kbindex"]
    : ["ps", "-aq", "--filter", "label=com.docker.compose.project=kbindex"]);
  const ids = containers.stdout.split(/\r?\n/).map((line: string) => line.trim()).filter(Boolean);
  if (ids.length > 0) {
    const args = launch.mode === "wsl" ? ["-e", "docker", "rm", "-f", ...ids] : ["rm", "-f", ...ids];
    await spawnExec(launch.command, args);
  }
  const remove = volumesToRemove(names, deletePostgres);
  if (remove.length > 0) {
    const args = launch.mode === "wsl" ? ["-e", "docker", "volume", "rm", ...remove] : ["volume", "rm", ...remove];
    await spawnExec(launch.command, args);
  }
}

async function startStack(win: BrowserWindow, clonePath: string): Promise<void> {
  const missing = missingCloneFiles(cloneMarkerNames(clonePath));
  if (missing.length > 0) {
    showStatus(win, `このフォルダには ${missing.join(", ")} がありません。`);
    return;
  }
  ensureEnv(clonePath);
  const launch = await detectDocker(spawnExec, process.platform);
  if ("error" in launch) {
    showStatus(win, `docker を確認できません。\n${launch.error}`);
    return;
  }
  showStatus(win, "スタックを起動しています。");
  const up = composeUpArgs(launch, clonePath);
  const started = await spawnExec(up.command, up.args, up.cwd);
  if (started.code !== 0) {
    showStatus(win, `docker compose up が失敗しました。\n${started.stderr || started.stdout}`);
    return;
  }
  const health = await pollHealth(async () => {
    const response = await fetch(HEALTH_URL);
    return response.json() as Promise<unknown>;
  }, (ms: number) => new Promise((resolve) => {
    setTimeout(resolve, ms);
  }));
  const embedding = health.services.embedding ?? "unknown";
  if (!health.ready) {
    showStatus(win, `起動が完了しませんでした（${Math.round(health.elapsedMs / 1000)}秒）。\nstatus=${health.status}\nembedding=${embedding}\n${health.error}`);
    return;
  }
  showStatus(win, `起動しました（${Math.round(health.elapsedMs / 1000)}秒）。embedding は ${embedding} です。`);
  loadApp(win);
}

ipcMain.handle("localrag:clone-path", () => readSavedClone(app.getPath("userData")));

ipcMain.handle("localrag:pick-clone", async (event) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  const folder = await pickClone(win);
  if (!folder) {
    return { ok: false, canceled: true, path: null, error: null };
  }
  const missing = missingCloneFiles(cloneMarkerNames(folder));
  if (missing.length > 0) {
    return { ok: false, canceled: false, path: folder, error: missing.join(", ") };
  }
  writeSavedClone(app.getPath("userData"), folder);
  return { ok: true, canceled: false, path: folder, error: null };
});

void app.whenReady().then(async () => {
  if (process.argv.includes("--uninstall-stack")) {
    await removeStack(process.argv.includes("delete-postgres"));
    app.exit(0);
    return;
  }
  const win = createWindow();
  if (process.env.ELECTRON_RENDERER_URL) {
    loadApp(win);
    return;
  }
  let clonePath = readSavedClone(app.getPath("userData"));
  if (!clonePath) {
    clonePath = await pickClone(win);
    if (!clonePath) {
      showStatus(win, "フォルダが選ばれていないので、起動できません。");
      return;
    }
    const missing = missingCloneFiles(cloneMarkerNames(clonePath));
    if (missing.length > 0) {
      showStatus(win, `このフォルダには ${missing.join(", ")} がありません。`);
      return;
    }
    writeSavedClone(app.getPath("userData"), clonePath);
  }
  await startStack(win, clonePath);
});

app.on("window-all-closed", () => {
  app.quit();
});
