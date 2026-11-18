import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import { createServer, type Server } from "node:http";
import path from "node:path";
import { _electron as electron } from "playwright";
import { expect, test } from "@playwright/test";

const root = path.resolve(import.meta.dirname, "..");
const rendererPort = 43242;

type SavedBody = { folders: string[]; includeSubfolders: boolean; autoIndex: boolean };

function listen(): Promise<{ server: Server; port: number; saved: SavedBody[] }> {
  const saved: SavedBody[] = [];
  const server = createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      const url = req.url ?? "";
      const headers = {
        "content-type": "application/json",
        "access-control-allow-origin": "*",
        "access-control-allow-methods": "GET, PUT, POST, OPTIONS",
        "access-control-allow-headers": "content-type",
      };
      if (req.method === "OPTIONS") {
        res.writeHead(204, headers);
        res.end();
        return;
      }
      if (req.method === "GET" && url.startsWith("/api/v1/settings/local")) {
        res.writeHead(200, headers);
        res.end(JSON.stringify({ folders: [], includeSubfolders: true, autoIndex: true }));
        return;
      }
      if (req.method === "PUT" && url.startsWith("/api/v1/settings/local")) {
        saved.push(JSON.parse(Buffer.concat(chunks).toString() || "{}") as SavedBody);
        res.writeHead(500, headers);
        res.end(JSON.stringify({ error: "down" }));
        return;
      }
      if (req.method === "GET" && url.startsWith("/api/v1/kb")) {
        res.writeHead(200, headers);
        res.end(JSON.stringify({ knowledgeBases: [] }));
        return;
      }
      res.writeHead(404, headers);
      res.end();
    });
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      resolve({ server, port, saved });
    });
  });
}

async function waitForRenderer(url: string): Promise<void> {
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) {
        return;
      }
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
  }
  throw new Error("renderer did not start");
}

test("a failed toggle stays on the saved value and a retry sends that change again", async () => {
  test.setTimeout(90_000);
  execFileSync("npx", ["tsc", "-p", "tsconfig.electron.json"], { cwd: root, stdio: "inherit" });
  const api = await listen();
  const renderer = `http://127.0.0.1:${rendererPort}`;
  const vite: ChildProcess = spawn(
    path.join(root, "node_modules", ".bin", "vite"),
    ["--host", "127.0.0.1", "--port", String(rendererPort), "--strictPort"],
    {
      cwd: root,
      env: { ...process.env, VITE_API_BASE: `http://127.0.0.1:${api.port}` },
      stdio: "pipe",
      detached: true,
    },
  );
  let app: Awaited<ReturnType<typeof electron.launch>> | undefined;
  try {
    await waitForRenderer(renderer);
    app = await electron.launch({
      args: [path.join(root, "dist-electron", "main.js")],
      cwd: root,
      env: { ...process.env, ELECTRON_RENDERER_URL: renderer },
    });
    const page = await app.firstWindow();
    const subfolders = page.getByRole("button", { name: "下の階層も含める" });
    await expect(subfolders).toBeVisible();
    await subfolders.click();
    await expect(page.getByText("PUT /api/v1/settings/local returned 500")).toBeVisible();
    await expect(page.getByRole("button", { name: "下の階層も含める" })).toBeVisible();
    await page.getByRole("button", { name: "下の階層も含める" }).click();
    await expect.poll(() => api.saved.map((body) => body.includeSubfolders)).toEqual([false, false]);

    await page.getByRole("button", { name: "索引" }).click();
    const autoIndex = page.getByRole("button", { name: "自動索引を止める" });
    await expect(autoIndex).toBeVisible();
    await autoIndex.click();
    await expect(page.getByRole("button", { name: "自動索引を止める" })).toBeVisible();
    await page.getByRole("button", { name: "自動索引を止める" }).click();
    await expect.poll(() => api.saved.slice(2).map((body) => body.autoIndex)).toEqual([false, false]);
  } finally {
    await app?.close();
    if (vite.pid) {
      try {
        process.kill(-vite.pid, "SIGTERM");
      } catch {
        vite.kill("SIGTERM");
      }
    }
    await new Promise<void>((resolve) => api.server.close(() => resolve()));
  }
});
