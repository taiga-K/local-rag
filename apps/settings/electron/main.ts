import { app, BrowserWindow, ipcMain, shell } from "electron";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { kbIdFor, syncAll, type FolderResult } from "./folderSync.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const API_BASE = process.env.KBINDEX_API ?? "http://127.0.0.1:43123";
const AUTO_SYNC_MS = 30_000;

let running: Promise<FolderResult[]> | null = null;
let again = false;

function runSync(): Promise<FolderResult[]> {
  if (running) {
    again = true;
    return running;
  }
  running = (async () => {
    try {
      let results: FolderResult[];
      do {
        again = false;
        results = await syncAll(API_BASE);
      } while (again);
      return results;
    } finally {
      running = null;
    }
  })();
  return running;
}

async function autoSync(): Promise<void> {
  try {
    const response = await fetch(`${API_BASE}/api/v1/settings/local`);
    const body = (await response.json()) as { autoIndex?: unknown };
    if (body.autoIndex !== false) {
      await runSync();
    }
  } catch {
    /* the API is not up yet */
  }
}

ipcMain.handle("localrag:sync-folders", async () => {
  try {
    const results = await runSync();
    return { ok: results.every((item) => item.errors.length === 0), results, error: null };
  } catch (error) {
    return { ok: false, results: [], error: error instanceof Error ? error.message : String(error) };
  }
});

// Drops every configured path of the KB and lets any running scan finish
// before detaching, so no push lands after the records are removed.
ipcMain.handle("localrag:detach-folder", async (_event, kbId: unknown) => {
  if (typeof kbId !== "string" || !kbId) {
    return { ok: false, error: "kb" };
  }
  try {
    const current = await fetch(`${API_BASE}/api/v1/settings/local`);
    const settings = (await current.json().catch(() => ({}))) as { folders?: unknown; includeSubfolders?: unknown; autoIndex?: unknown };
    if (!current.ok || !Array.isArray(settings.folders)) {
      return { ok: false, error: `settings: HTTP ${current.status}` };
    }
    const folders = settings.folders.filter((item): item is string => typeof item === "string");
    const saved = await fetch(`${API_BASE}/api/v1/settings/local`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        folders: folders.filter((folder) => kbIdFor(folder) !== kbId),
        includeSubfolders: settings.includeSubfolders !== false,
        autoIndex: settings.autoIndex !== false,
      }),
    });
    if (!saved.ok) {
      return { ok: false, error: `settings: HTTP ${saved.status}` };
    }
    await runSync().catch(() => []);
    const detached = await fetch(`${API_BASE}/api/v1/kb/${encodeURIComponent(kbId)}/detach`, { method: "POST" });
    return { ok: detached.ok, error: detached.ok ? null : `detach: HTTP ${detached.status}` };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
});

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

function createWindow(): void {
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
  const devUrl = process.env.ELECTRON_RENDERER_URL;
  if (devUrl) {
    void win.loadURL(devUrl);
    return;
  }
  void win.loadURL(pathToFileURL(path.join(here, "../dist/index.html")).href);
}

void app.whenReady().then(() => {
  createWindow();
  void autoSync();
  setInterval(() => void autoSync(), AUTO_SYNC_MS);
});
app.on("window-all-closed", () => {
  app.quit();
});
