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

const QDRANT_UNAVAILABLE = "検索用のデータベースに接続できませんでした。local-rag を起動し直してから、再試行してください。";
const NO_STORED_FAILURE = "このファイルを読み込めませんでした。ファイルが開けるか確かめてから、再試行してください。";
const ONE_NOTE = "この形式（.one）には対応していません。OneNote から PDF か Word で書き出すと取り込めます。";
const TIMED_OUT = "読み込みに時間がかかりすぎたため中断しました。しばらくしてから再試行してください。";
const LEGACY_NO_STORED = "原因が記録されていません。再試行しても失敗する場合はファイルを開けるか確かめてください。";

function isTimeout(text: string): boolean {
  return /timeout/i.test(text);
}

function isOneNote(name: string | undefined, text: string, classified: boolean): boolean {
  if (!name || !name.toLowerCase().endsWith(".one")) {
    return false;
  }
  return !classified || !text || text === "INDEX_FAILED" || text === LEGACY_NO_STORED;
}

export function failureLine(classified: boolean, message: string | null, name?: string): string {
  const text = (message ?? "").trim();
  if (text === "QDRANT_UNAVAILABLE") {
    return QDRANT_UNAVAILABLE;
  }
  if (isTimeout(text)) {
    return TIMED_OUT;
  }
  if (isOneNote(name, text, classified)) {
    return ONE_NOTE;
  }
  if (!classified || !text || text === "INDEX_FAILED" || text === LEGACY_NO_STORED) {
    return NO_STORED_FAILURE;
  }
  const chars = Array.from(text);
  return chars.length <= 160 ? text : chars.slice(0, 160).join("");
}

export function failureShort(classified: boolean, message: string | null, name?: string): string {
  const text = (message ?? "").trim();
  if (text === "QDRANT_UNAVAILABLE") {
    return "データベースに接続できません";
  }
  if (isTimeout(text)) {
    return "読み込みが時間切れ";
  }
  if (isOneNote(name, text, classified)) {
    return "対応していない形式（.one）";
  }
  return "読み込めませんでした";
}

export function remainingOf(row: { queued: number; active: number }): number {
  return row.queued + row.active;
}

export function statusLabel(status: string): string {
  switch (status) {
    case "COMPLETED":
      return "取り込み済み";
    case "IN_PROGRESS":
      return "取り込み中";
    case "QUEUED":
      return "待ち";
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

export function statusBarLabel(summary: { active: number; queued: number }): string {
  const remaining = summary.active + summary.queued;
  return remaining > 0 ? `残り${remaining}件` : "すべて取り込み済み";
}

export function resultLabel(status: string): string {
  switch (status) {
    case "COMPLETED":
    case "EMPTY":
      return "取り込み済み";
    case "IN_PROGRESS":
      return "取り込み中";
    case "FAILED":
      return "失敗";
    case "QUEUED":
      return "待ち";
    default:
      return statusLabel(status);
  }
}

export function folderCountItems(folder: {
  completed: number;
  active: number;
  failed: number;
  queued: number;
}): { key: string; label: string; count: number }[] {
  return [
    { key: "completed", label: "取り込み済み", count: folder.completed },
    { key: "queued", label: "待ち", count: folder.queued },
    { key: "active", label: "取り込み中", count: folder.active },
    { key: "failed", label: "失敗", count: folder.failed },
  ];
}

export function folderSentence(folder: {
  total: number;
  completed: number;
  active: number;
  failed: number;
  queued: number;
  held?: number;
  empty?: number;
}): string {
  if (folder.total === 0) {
    return "ファイルはありません。";
  }
  const held = folder.held ?? 0;
  const empty = folder.empty ?? 0;
  if (folder.active === 0 && folder.failed === 0 && folder.queued === 0 && held === 0) {
    return `${folder.total}件を取り込み済みです。`;
  }
  const parts = [`${folder.completed}件を取り込み済み`];
  if (folder.queued > 0) {
    parts.push(`${folder.queued}件は取り込み待ち`);
  }
  if (folder.active > 0) {
    parts.push(`${folder.active}件は取り込み中`);
  }
  if (folder.failed > 0) {
    parts.push(`${folder.failed}件は取り込めませんでした`);
  }
  if (held > 0) {
    parts.push(`${held}件は自動取り込みを止めています`);
  }
  if (empty > 0) {
    parts.push(`${empty}件は本文がありません`);
  }
  return `${folder.total}件のうち${parts.join("、")}。`;
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
