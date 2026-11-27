export type OpenPathResult = { ok: boolean; error: string | null };
export type PickFolderResult = { ok: boolean; canceled: boolean; path: string | null; error: string | null };

type LocalRagBridge = {
  openPath: (folder: string) => Promise<OpenPathResult>;
  pickFolder: () => Promise<PickFolderResult>;
  clonePath?: () => Promise<string | null>;
  pickClone?: () => Promise<PickFolderResult>;
};

export type CloneBridge = {
  clonePath: () => Promise<string | null>;
  pickClone: () => Promise<PickFolderResult>;
};

export function folderBridge(): LocalRagBridge | null {
  const candidate = (window as Window & { localrag?: LocalRagBridge }).localrag;
  if (!candidate || typeof candidate.openPath !== "function" || typeof candidate.pickFolder !== "function") {
    return null;
  }
  return candidate;
}

export function cloneBridge(): CloneBridge | null {
  const candidate = (window as Window & { localrag?: LocalRagBridge }).localrag;
  if (!candidate || typeof candidate.clonePath !== "function" || typeof candidate.pickClone !== "function") {
    return null;
  }
  return { clonePath: candidate.clonePath, pickClone: candidate.pickClone };
}

export function folderPathKey(folder: string): string {
  let end = folder.length;
  while (end > 1 && (folder[end - 1] === "/" || folder[end - 1] === "\\")) {
    const withoutSeparator = folder.slice(0, end - 1);
    if (/^[A-Za-z]:$/.test(withoutSeparator)) {
      break;
    }
    end -= 1;
  }
  return folder.slice(0, end);
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
