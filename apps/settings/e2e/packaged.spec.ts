import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { _electron as electron } from "playwright";
import { expect, test } from "@playwright/test";

const root = path.resolve(import.meta.dirname, "..");

test("packaged window shows the settings heading from file://", async () => {
  test.setTimeout(180_000);
  execFileSync("npm", ["run", "build"], { cwd: root, stdio: "inherit", env: process.env });
  const html = fs.readFileSync(path.join(root, "dist", "index.html"), "utf8");
  expect(html).not.toContain("crossorigin");
  const env = { ...process.env };
  delete env.ELECTRON_RENDERER_URL;
  const app = await electron.launch({
    args: [path.join(root, "dist-electron", "main.js")],
    cwd: root,
    env,
  });
  try {
    const page = await app.firstWindow();
    await expect(page.getByRole("heading", { name: "索引の設定" })).toBeVisible();
  } finally {
    await app.close();
  }
});
