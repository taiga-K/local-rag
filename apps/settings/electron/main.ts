import { app, BrowserWindow } from "electron";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

function createWindow(): void {
  const win = new BrowserWindow({
    width: 960,
    height: 720,
    webPreferences: { contextIsolation: true, sandbox: true },
  });
  const devUrl = process.env.ELECTRON_RENDERER_URL;
  if (devUrl) {
    void win.loadURL(devUrl);
    return;
  }
  void win.loadURL(pathToFileURL(path.join(here, "../dist/index.html")).href);
}

void app.whenReady().then(createWindow);
app.on("window-all-closed", () => {
  app.quit();
});
