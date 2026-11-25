import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { blocksFor, decodeText, externalIdFor, kbIdFor, kbNameFor, listFiles, recordNameFor, syncFolder } from "./folderSync";

type Call = { method: string; url: string; body: any };

function fakeApi(records: { externalRecordId: string; version: number }[] = []) {
  const calls: Call[] = [];
  const fetcher = (async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ method, url, body });
    let status = 200;
    let payload: unknown = {};
    if (method === "POST" && url.endsWith("/api/v1/kb")) {
      status = 201;
      payload = body;
    } else if (method === "GET" && url.includes("/records?")) {
      payload = { records: url.includes("offset=0") ? records : [] };
    } else if (method === "POST" && url.endsWith("/records")) {
      payload = { status: "created" };
    } else if (method === "DELETE") {
      payload = { deleted: true };
    }
    return new Response(JSON.stringify(payload), { status });
  }) as typeof fetch;
  return { calls, fetcher };
}

let root: string;

beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), "folder-sync-"));
});

afterEach(() => {
  fs.rmSync(root, { recursive: true, force: true });
});

describe("folder sync", () => {
  it("gives each Windows folder one id regardless of case and trailing slash", () => {
    expect(kbIdFor("C:\\Users\\taiga\\Docs", "win32")).toBe(kbIdFor("c:/users/taiga/docs/", "win32"));
    expect(kbIdFor("C:\\Users\\taiga\\Docs", "win32")).toMatch(/^local-[0-9a-f]{24}$/);
    expect(kbNameFor("C:\\Users\\taiga\\議事録")).toBe("議事録");
  });

  it("keeps Japanese file names apart and inside the id pattern", () => {
    const a = externalIdFor("議事録.md");
    const b = externalIdFor("報告書.md");
    expect(a).not.toBe(b);
    expect(a).toMatch(/^[A-Za-z0-9][A-Za-z0-9._~:-]{0,255}$/);
    expect(recordNameFor("50%s <b>.txt")).toBe("50％s _b_.txt");
  });

  it("reads Shift_JIS when the bytes are not UTF-8", () => {
    const sjis = Uint8Array.from([0x93, 0x8c, 0x8b, 0x9e]);
    expect(decodeText(sjis)).toBe("東京");
    expect(decodeText(new TextEncoder().encode("天気"))).toBe("天気");
  });

  it("turns markdown and html into blocks", () => {
    const md = blocksFor("a.md", "# 見出し\n本文\n\n次の段落");
    expect(md.blocks.map((block) => block.sub_type)).toEqual(["heading", "paragraph", "paragraph"]);
    expect(md.block_groups?.[0].children).toEqual({ block_ranges: [{ start: 0, end: 2 }] });
    const html = blocksFor("a.html", "<style>x</style><h1>題</h1><p>山手線&amp;池袋</p><li>項目</li>");
    expect(html.blocks.map((block) => [block.sub_type, block.data])).toEqual([
      ["heading", "題"],
      ["paragraph", "山手線&池袋"],
      ["list_item", "項目"],
    ]);
  });

  it("lists supported files and honors includeSubfolders", () => {
    fs.writeFileSync(path.join(root, "a.txt"), "a");
    fs.writeFileSync(path.join(root, "b.pdf"), "b");
    fs.writeFileSync(path.join(root, ".hidden.md"), "h");
    fs.mkdirSync(path.join(root, "sub"));
    fs.writeFileSync(path.join(root, "sub", "c.md"), "c");
    expect(listFiles(root, true).map((file) => file.rel)).toEqual(["a.txt", "sub/c.md"]);
    expect(listFiles(root, false).map((file) => file.rel)).toEqual(["a.txt"]);
  });

  it("pushes new files, skips unchanged ones, and deletes missing ones", async () => {
    fs.writeFileSync(path.join(root, "天気.txt"), "東京都の今日の天気は晴れです。");
    fs.writeFileSync(path.join(root, "old.txt"), "same");
    const old = listFiles(root, true).find((file) => file.rel === "old.txt")!;
    const api = fakeApi([
      { externalRecordId: externalIdFor("old.txt"), version: Math.floor(old.mtimeMs * 1000) },
      { externalRecordId: externalIdFor("gone.txt"), version: 1 },
    ]);
    const result = await syncFolder("http://api", root, true, api.fetcher);
    expect(result).toMatchObject({ pushed: 1, unchanged: 1, deleted: 1, errors: [] });
    const push = api.calls.find((call) => call.method === "POST" && call.url.endsWith("/records"))!;
    expect(push.url).toBe(`http://api/api/v1/kb/${kbIdFor(root)}/records`);
    expect(push.body).toMatchObject({
      recordName: "天気.txt",
      mimeType: "application/blocks",
      externalRecordId: externalIdFor("天気.txt"),
      blocksFormat: 1,
      blocks: { blocks: [{ index: 0, type: "text", format: "txt", data: "東京都の今日の天気は晴れです。" }] },
    });
    const removed = api.calls.find((call) => call.method === "DELETE")!;
    expect(removed.url).toContain(`/records/${externalIdFor("gone.txt")}?source=sync`);
  });

  it("does not delete anything when the folder cannot be read", async () => {
    const api = fakeApi([{ externalRecordId: externalIdFor("a.txt"), version: 1 }]);
    const result = await syncFolder("http://api", path.join(root, "missing"), true, api.fetcher);
    expect(result.errors).toHaveLength(1);
    expect(api.calls).toEqual([]);
  });

  it.skipIf(process.getuid?.() === 0)("keeps records under a subfolder it cannot list", async () => {
    const locked = path.join(root, "locked");
    fs.mkdirSync(locked);
    fs.writeFileSync(path.join(locked, "kept.txt"), "k");
    fs.chmodSync(locked, 0o000);
    try {
      const api = fakeApi([{ externalRecordId: externalIdFor("locked/kept.txt"), version: 1 }]);
      const result = await syncFolder("http://api", root, true, api.fetcher);
      expect(result.errors).toEqual(["locked: 読めません"]);
      expect(api.calls.some((call) => call.method === "DELETE")).toBe(false);
    } finally {
      fs.chmodSync(locked, 0o755);
    }
  });
});
