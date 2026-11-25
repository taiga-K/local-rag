export type OpenPathResult = { ok: boolean; error: string | null };

export type SyncFoldersResult = {
  ok: boolean;
  error: string | null;
  results: { folder: string; kbId: string; pushed: number; unchanged: number; deleted: number; errors: string[] }[];
};

type LocalRagBridge = {
  openPath: (folder: string) => Promise<OpenPathResult>;
  syncFolders?: () => Promise<SyncFoldersResult>;
  detachFolder?: (kbId: string) => Promise<OpenPathResult>;
};

export function folderBridge(): LocalRagBridge | null {
  const candidate = (window as Window & { localrag?: LocalRagBridge }).localrag;
  if (!candidate || typeof candidate.openPath !== "function") {
    return null;
  }
  return candidate;
}

export function configuredFolder(folders: string[], name: string): string | null {
  const match = folders.find((folder) => folder.replace(/\\/g, "/").split("/").filter(Boolean).pop() === name);
  if (match) {
    return match;
  }
  if (folders.length === 1) {
    return folders[0];
  }
  return null;
}

export function syncError(result: SyncFoldersResult): string {
  if (result.error) {
    return result.error;
  }
  const first = result.results.flatMap((item) => item.errors)[0];
  return first ? `取り込めないファイルがあります: ${first}` : "";
}

export async function syncFolders(): Promise<string> {
  const bridge = folderBridge();
  if (!bridge?.syncFolders) {
    return "";
  }
  return syncError(await bridge.syncFolders());
}
