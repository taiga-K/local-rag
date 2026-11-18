export const SCREENS = [
  { id: "folders", title: "取り込むフォルダ" },
  { id: "index", title: "索引" },
  { id: "status", title: "取り込み状況" },
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

export type SettingsDraft = {
  folders: string;
  includeSubfolders: boolean;
  autoIndex: boolean;
};

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
