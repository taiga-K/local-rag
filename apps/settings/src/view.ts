export const SCREENS = [
  { id: "overview", title: "概要" },
  { id: "settings", title: "設定" },
] as const;

export type ScreenId = (typeof SCREENS)[number]["id"];

const STATUS_ORDER = ["QUEUED", "IN_PROGRESS", "COMPLETED", "FAILED", "EMPTY", "AUTO_INDEX_OFF"] as const;

export function parseFolders(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const line of text.split(/\r?\n/)) {
    const folder = line.trim();
    if (!folder || seen.has(folder)) {
      continue;
    }
    seen.add(folder);
    out.push(folder);
  }
  return out;
}

export function foldersText(folders: string[]): string {
  return folders.join("\n");
}

export function autoIndexCopy(on: boolean): { title: string; detail: string } {
  if (on) {
    return { title: "自動で索引する", detail: "取り込んだ文書はすぐ索引されます。" };
  }
  return { title: "選んだものだけ索引する", detail: "新しい文書は索引されず、再索引で進みます。" };
}

export function countRows(counts: Record<string, number>): { status: string; count: number }[] {
  return STATUS_ORDER.filter((status) => status in counts).map((status) => ({
    status,
    count: counts[status] ?? 0,
  }));
}

export function showsAdminControls(): false {
  return false;
}

export function failureLine(classified: boolean, message: string | null): string {
  if (classified && message) {
    return message;
  }
  return "理由は分類できません。";
}

export function statusLabel(status: string): string {
  switch (status) {
    case "COMPLETED":
      return "取り込み済み";
    case "IN_PROGRESS":
      return "取り込み中";
    case "QUEUED":
      return "取り込み待ち";
    case "FAILED":
      return "失敗";
    case "EMPTY":
      return "本文なし";
    case "AUTO_INDEX_OFF":
      return "自動取り込み停止";
    case "NOT_STARTED":
      return "未着手";
    default:
      return "分類できない状態";
  }
}

export function folderSentence(folder: { total: number; completed: number; active: number; failed: number; queued: number }): string {
  if (folder.total === 0) {
    return "ファイルはありません。";
  }
  if (folder.active === 0 && folder.failed === 0 && folder.queued === 0) {
    return `${folder.total}件を取り込み済みです。`;
  }
  return `${folder.total}件のうち${folder.completed}件を取り込み済み、${folder.active}件は取り込み中、${folder.failed}件は取り込めませんでした。`;
}

export function visibleRecords<T extends { recordName: string; indexingStatus: string }>(
  records: T[],
  query: string,
  failedOnly: boolean,
): T[] {
  const needle = query.trim().toLowerCase();
  return records.filter((row) => {
    if (failedOnly && row.indexingStatus !== "FAILED") {
      return false;
    }
    if (needle && !row.recordName.toLowerCase().includes(needle)) {
      return false;
    }
    return true;
  });
}

export type SettingsDraft = {
  folders: string;
  includeSubfolders: boolean;
  autoIndex: boolean;
};

export type SettingsField = "includeSubfolders" | "autoIndex" | "folders";

export type AppliedSettings = {
  folders?: string;
  includeSubfolders?: boolean;
  autoIndex?: boolean;
  message: string;
};

export class SettingsSaver {
  private tail: Promise<void> = Promise.resolve();

  save(
    readLatest: () => SettingsDraft,
    patch: Partial<SettingsDraft>,
    persist: (draft: SettingsDraft) => Promise<SettingsDraft>,
    field: SettingsField,
  ): Promise<AppliedSettings> {
    const run = this.tail.then(async (): Promise<AppliedSettings> => {
      const next = { ...readLatest(), ...patch };
      try {
        const saved = await persist(next);
        if (field === "folders") {
          return {
            folders: saved.folders,
            includeSubfolders: saved.includeSubfolders,
            autoIndex: saved.autoIndex,
            message: "保存しました",
          };
        }
        return { [field]: saved[field], message: "保存しました" };
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : "保存に失敗しました";
        return { message };
      }
    });
    this.tail = run.then(
      () => undefined,
      () => undefined,
    );
    return run;
  }
}

export async function commitSettingsChange(
  current: SettingsDraft,
  next: SettingsDraft,
  save: (value: SettingsDraft) => Promise<SettingsDraft>,
): Promise<{ value: SettingsDraft; message: string }> {
  try {
    const saved = await save(next);
    return { value: saved, message: "保存しました" };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "保存に失敗しました";
    return { value: current, message };
  }
}
