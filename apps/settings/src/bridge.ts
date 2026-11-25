export type OpenPathResult = { ok: boolean; error: string | null };
export type PickFolderResult = { ok: boolean; canceled: boolean; path: string | null; error: string | null };

type LocalRagBridge = {
  openPath: (folder: string) => Promise<OpenPathResult>;
  pickFolder: () => Promise<PickFolderResult>;
};

export function folderBridge(): LocalRagBridge | null {
  const candidate = (window as Window & { localrag?: LocalRagBridge }).localrag;
  if (!candidate || typeof candidate.openPath !== "function" || typeof candidate.pickFolder !== "function") {
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
