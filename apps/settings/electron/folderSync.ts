// The API runs in Docker and cannot read the user's disk, so the desktop app
// reads the chosen folders and pushes each file as blocks.
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

export const EXTENSIONS = new Set([".txt", ".md", ".markdown", ".html", ".htm"]);
const MAX_VERSION = Number.MAX_SAFE_INTEGER;

export type LocalSettings = { folders: string[]; includeSubfolders: boolean; autoIndex: boolean };
export type FolderFile = { full: string; rel: string; mtimeMs: number };
export type FolderResult = {
  folder: string;
  kbId: string;
  pushed: number;
  unchanged: number;
  deleted: number;
  errors: string[];
};

type Block = Record<string, unknown>;
type Blocks = { blocks: Block[]; block_groups?: Block[] };
type Fetch = typeof fetch;

function folderKey(folder: string, platform: NodeJS.Platform = process.platform): string {
  const resolved = platform === "win32" ? path.win32.resolve(folder) : path.posix.resolve(folder);
  const slashed = resolved.replace(/\\/g, "/").replace(/\/+$/, "") || "/";
  return platform === "win32" ? slashed.toLowerCase() : slashed;
}

export function kbIdFor(folder: string, platform: NodeJS.Platform = process.platform): string {
  return `local-${createHash("sha256").update(folderKey(folder, platform)).digest("hex").slice(0, 24)}`;
}

export function kbNameFor(folder: string): string {
  const name = folder.replace(/\\/g, "/").split("/").filter(Boolean).pop() ?? folder;
  return (name || folder).slice(0, 255);
}

export function externalIdFor(rel: string): string {
  return `f-${createHash("sha256").update(rel).digest("hex").slice(0, 40)}`;
}

export function recordNameFor(fileName: string): string {
  const cleaned = fileName.replace(/[<>]/g, "_").replace(/%/g, "％").trim();
  return (cleaned || "doc").slice(0, 255);
}

// Epoch microseconds, as kbindex-ingest sync uses.
export function versionOf(mtimeMs: number): number {
  return Math.min(Math.max(Math.floor(mtimeMs * 1000), 0), MAX_VERSION);
}

export function listFiles(root: string, includeSubfolders: boolean): FolderFile[] {
  const out: FolderFile[] = [];
  const walk = (dir: string) => {
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      if (entry.name.startsWith(".") || entry.name.startsWith("~$")) {
        continue;
      }
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (includeSubfolders) {
          walk(full);
        }
        continue;
      }
      if (!entry.isFile() || !EXTENSIONS.has(path.extname(entry.name).toLowerCase())) {
        continue;
      }
      try {
        const stat = fs.statSync(full);
        out.push({ full, rel: path.relative(root, full).split(path.sep).join("/"), mtimeMs: stat.mtimeMs });
      } catch {
        /* removed while scanning */
      }
    }
  };
  walk(root);
  return out.sort((a, b) => a.rel.localeCompare(b.rel));
}

export function decodeText(bytes: Uint8Array): string {
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    try {
      return new TextDecoder("shift_jis").decode(bytes);
    } catch {
      return new TextDecoder("utf-8").decode(bytes);
    }
  }
}

export function blocksFor(fileName: string, text: string): Blocks {
  const ext = path.extname(fileName).toLowerCase();
  if (ext === ".md" || ext === ".markdown") {
    return markdownBlocks(text);
  }
  if (ext === ".html" || ext === ".htm") {
    return htmlBlocks(text);
  }
  return { blocks: [{ index: 0, type: "text", format: "txt", data: text }] };
}

function markdownBlocks(text: string): Blocks {
  const items: ["h" | "p", string][] = [];
  let buffer: string[] = [];
  const flush = () => {
    const value = buffer.join("\n").trim();
    buffer = [];
    if (value) {
      items.push(["p", value]);
    }
  };
  for (const line of text.split(/\r?\n/)) {
    const heading = /^#{1,6}\s+(\S.*)$/.exec(line);
    if (heading) {
      flush();
      items.push(["h", heading[1].trim()]);
    } else if (!line.trim()) {
      flush();
    } else {
      buffer.push(line);
    }
  }
  flush();
  const blocks: Block[] = [];
  const starts: number[] = [];
  for (const [kind, value] of items) {
    if (kind === "h") {
      starts.push(blocks.length);
    }
    blocks.push({
      index: blocks.length,
      type: "text",
      format: "markdown",
      sub_type: kind === "h" ? "heading" : "paragraph",
      data: value,
    });
  }
  const groups: Block[] = starts.map((start, pos) => {
    const end = pos + 1 < starts.length ? starts[pos + 1] - 1 : blocks.length - 1;
    for (let index = start; index <= end; index += 1) {
      blocks[index].parent_index = pos;
    }
    return {
      index: pos,
      type: "text_section",
      name: String(blocks[start].data).slice(0, 1024),
      children: { block_ranges: [{ start, end }] },
    };
  });
  if (blocks.length === 0) {
    return { blocks: [{ index: 0, type: "text", format: "markdown", data: "" }] };
  }
  return groups.length ? { blocks, block_groups: groups } : { blocks };
}

const ENTITIES: Record<string, string> = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };

function htmlText(fragment: string): string {
  return fragment
    .replace(/<[^>]*>/g, " ")
    .replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (whole, name: string) => {
      if (name[0] === "#") {
        const code = name[1] === "x" || name[1] === "X" ? parseInt(name.slice(2), 16) : parseInt(name.slice(1), 10);
        return Number.isFinite(code) && code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : whole;
      }
      return ENTITIES[name.toLowerCase()] ?? whole;
    })
    .replace(/\s+/g, " ")
    .trim();
}

function htmlBlocks(text: string): Blocks {
  const body = text.replace(/<!--[\s\S]*?-->/g, " ").replace(/<(script|style)\b[\s\S]*?<\/\1\s*>/gi, " ");
  const blocks: Block[] = [];
  for (const match of body.matchAll(/<(h[1-3]|p|li)\b[^>]*>([\s\S]*?)<\/\1\s*>/gi)) {
    const value = htmlText(match[2]);
    if (!value) {
      continue;
    }
    const tag = match[1].toLowerCase();
    const kind = tag.startsWith("h") ? "heading" : tag === "li" ? "list_item" : "paragraph";
    blocks.push({ index: blocks.length, type: "text", format: "html", data: value, sub_type: kind });
  }
  if (blocks.length === 0) {
    return { blocks: [{ index: 0, type: "text", format: "html", data: htmlText(body) }] };
  }
  return { blocks };
}

async function call(fetcher: Fetch, method: string, url: string, body?: unknown): Promise<{ status: number; json: any }> {
  const response = await fetcher(url, {
    method,
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const raw = await response.text();
  let json: any = {};
  try {
    json = raw ? JSON.parse(raw) : {};
  } catch {
    json = {};
  }
  return { status: response.status, json };
}

function failure(label: string, status: number, json: any): string {
  const message = json?.error?.message ?? json?.message ?? "";
  return `${label}: HTTP ${status}${message ? ` ${message}` : ""}`;
}

async function serverVersions(fetcher: Fetch, api: string, kbId: string): Promise<Map<string, number>> {
  const versions = new Map<string, number>();
  const pageSize = 200;
  for (let offset = 0; ; offset += pageSize) {
    const { status, json } = await call(fetcher, "GET", `${api}/api/v1/kb/${encodeURIComponent(kbId)}/records?limit=${pageSize}&offset=${offset}`);
    if (status !== 200) {
      throw new Error(failure("records", status, json));
    }
    const rows: { externalRecordId: string; version: number }[] = json.records ?? [];
    for (const row of rows) {
      versions.set(row.externalRecordId, Number(row.version));
    }
    if (rows.length < pageSize) {
      return versions;
    }
  }
}

export async function syncFolder(
  api: string,
  folder: string,
  includeSubfolders: boolean,
  fetcher: Fetch = fetch,
): Promise<FolderResult> {
  const kbId = kbIdFor(folder);
  const result: FolderResult = { folder, kbId, pushed: 0, unchanged: 0, deleted: 0, errors: [] };
  let isDirectory = false;
  try {
    isDirectory = fs.statSync(folder).isDirectory();
  } catch {
    isDirectory = false;
  }
  if (!isDirectory) {
    result.errors.push(`${folder}: フォルダを読めません`);
    return result;
  }
  const created = await call(fetcher, "POST", `${api}/api/v1/kb`, { id: kbId, name: kbNameFor(folder) });
  if (created.status !== 200 && created.status !== 201) {
    result.errors.push(failure(folder, created.status, created.json));
    return result;
  }
  const known = await serverVersions(fetcher, api, kbId);
  const seen = new Set<string>();
  for (const file of listFiles(folder, includeSubfolders)) {
    const external = externalIdFor(file.rel);
    seen.add(external);
    const previous = known.get(external) ?? null;
    const version = versionOf(file.mtimeMs);
    if (previous !== null && version <= previous) {
      result.unchanged += 1;
      continue;
    }
    let text: string;
    try {
      text = decodeText(fs.readFileSync(file.full));
    } catch {
      result.errors.push(`${file.rel}: 読めません`);
      continue;
    }
    const envelope = {
      recordName: recordNameFor(path.basename(file.full)),
      mimeType: "application/blocks",
      externalRecordId: external,
      version,
      blocksFormat: 1,
      sourceLastModifiedTimestamp: Math.max(1, Math.floor(file.mtimeMs)),
      blocks: blocksFor(file.full, text),
    };
    const pushed = await call(fetcher, "POST", `${api}/api/v1/kb/${encodeURIComponent(kbId)}/records`, envelope);
    if (pushed.status >= 200 && pushed.status < 300) {
      if (pushed.json?.status === "unchanged") {
        result.unchanged += 1;
      } else {
        result.pushed += 1;
      }
    } else {
      result.errors.push(failure(file.rel, pushed.status, pushed.json));
    }
  }
  for (const external of known.keys()) {
    if (seen.has(external)) {
      continue;
    }
    const removed = await call(
      fetcher,
      "DELETE",
      `${api}/api/v1/kb/${encodeURIComponent(kbId)}/records/${encodeURIComponent(external)}?source=sync`,
    );
    if (removed.status === 200 || removed.status === 404) {
      result.deleted += 1;
    } else {
      result.errors.push(failure(external, removed.status, removed.json));
    }
  }
  return result;
}

export async function syncAll(api: string, fetcher: Fetch = fetch): Promise<FolderResult[]> {
  const { status, json } = await call(fetcher, "GET", `${api}/api/v1/settings/local`);
  if (status !== 200) {
    throw new Error(failure("settings", status, json));
  }
  const settings = json as LocalSettings;
  const results: FolderResult[] = [];
  for (const folder of settings.folders ?? []) {
    try {
      results.push(await syncFolder(api, folder, settings.includeSubfolders !== false, fetcher));
    } catch (error) {
      results.push({
        folder,
        kbId: kbIdFor(folder),
        pushed: 0,
        unchanged: 0,
        deleted: 0,
        errors: [error instanceof Error ? error.message : String(error)],
      });
    }
  }
  return results;
}
