import { execFileSync } from "node:child_process";
import { createServer, type Server } from "node:http";
import { spawn, type ChildProcess } from "node:child_process";
import path from "node:path";
import { _electron as electron } from "playwright";
import { expect, test } from "@playwright/test";

const root = path.resolve(import.meta.dirname, "..");
const rendererPort = 43241;

type SavedBody = { folders: string[]; includeSubfolders: boolean; autoIndex: boolean };

function listen(): Promise<{ server: Server; port: number; saved: SavedBody[]; reads: number }> {
  const saved: SavedBody[] = [];
  let reads = 0;
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
        reads += 1;
        res.writeHead(200, headers);
        res.end(JSON.stringify({ folders: [], includeSubfolders: true, autoIndex: true }));
        return;
      }
      if (req.method === "PUT" && url.startsWith("/api/v1/settings/local")) {
        const body = JSON.parse(Buffer.concat(chunks).toString() || "{}") as SavedBody;
        saved.push(body);
        res.writeHead(200, headers);
        res.end(JSON.stringify(body));
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
      resolve({
        server,
        port,
        saved,
        get reads() {
          return reads;
        },
      });
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

test("folder field is a textarea and one path per line is saved", async () => {
  test.setTimeout(90_000);
  execFileSync("npx", ["tsc", "-p", "tsconfig.electron.json"], { cwd: root, stdio: "inherit" });
  const api = await listen();
  const renderer = `http://127.0.0.1:${rendererPort}`;
  const vite: ChildProcess = spawn(path.join(root, "node_modules", ".bin", "vite"), ["--host", "127.0.0.1", "--port", String(rendererPort), "--strictPort"], {
    cwd: root,
    env: { ...process.env, VITE_API_BASE: `http://127.0.0.1:${api.port}` },
    stdio: "pipe",
    detached: true,
  });
  let app: Awaited<ReturnType<typeof electron.launch>> | undefined;
  try {
    await waitForRenderer(renderer);
    const env = { ...process.env, ELECTRON_RENDERER_URL: renderer };
    app = await electron.launch({
      args: [path.join(root, "dist-electron", "main.js")],
      cwd: root,
      env,
    });
    const page = await app.firstWindow();
    await expect.poll(() => api.reads).toBeGreaterThan(0);
    const folder = page.getByLabel("フォルダ");
    expect(await folder.evaluate((el) => el.tagName)).toBe("TEXTAREA");
    expect(await folder.getAttribute("rows")).toBe("4");
    await folder.fill("/data/a\n/data/b");
    await page.getByRole("button", { name: "保存" }).click();
    await expect.poll(() => api.saved).toEqual([
      { folders: ["/data/a", "/data/b"], includeSubfolders: true, autoIndex: true },
    ]);
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
