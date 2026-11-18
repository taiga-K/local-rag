import { _electron as electron } from "playwright";
import { expect, test } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const renderer = "http://127.0.0.1:43124";

async function waitForRenderer(): Promise<void> {
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(renderer);
      if (response.ok) {
        return;
      }
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
  }
  throw new Error("renderer did not start");
}

test("saves a folder and reads indexing status", async () => {
  const vite: ChildProcess = spawn("npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", "43124"], {
    cwd: root,
    stdio: "pipe",
  });
  try {
    await waitForRenderer();
    const app = await electron.launch({
      args: [path.join(root, "dist-electron", "main.js")],
      cwd: root,
      env: { ...process.env, ELECTRON_RENDERER_URL: renderer },
    });
    const page = await app.firstWindow();
    await page.getByRole("button", { name: "取り込むフォルダ" }).click();
    const folder = page.getByLabel("フォルダ");
    await folder.fill("/tmp/kbindex-settings-e2e");
    await page.getByRole("button", { name: "保存" }).click();
    await expect(page.getByText("保存しました")).toBeVisible();
    await page.getByRole("button", { name: "取り込み状況" }).click();
    await page.getByRole("button", { name: "状況を読む" }).click();
    const counts = page.getByText(/^(QUEUED|IN_PROGRESS|COMPLETED|FAILED|EMPTY|AUTO_INDEX_OFF) \d+$/);
    await expect(counts).toHaveCount(6);
    await app.close();
  } finally {
    await fetch("http://127.0.0.1:43123/api/v1/settings/local", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ folders: [], includeSubfolders: true, autoIndex: true }),
    }).catch(() => undefined);
    vite.kill("SIGTERM");
  }
});
