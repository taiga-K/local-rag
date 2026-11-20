import { describe, expect, it } from "vitest";
import { SCREENS, SettingsSaver, autoIndexCopy, commitSettingsChange, countRows, failureLine, folderSentence, foldersText, parseFolders, showsAdminControls, statusLabel, visibleRecords } from "./view";

describe("settings view", () => {
  it("keeps unique folder paths and drops blanks", () => {
    expect(parseFolders(" /data/a \n\n/data/a\n/data/b ")).toEqual(["/data/a", "/data/b"]);
    expect(foldersText(["/data/a"])).toBe("/data/a");
  });

  it("names the auto-index states a person can choose", () => {
    expect(autoIndexCopy(true).title).toBe("自動で索引する");
    expect(autoIndexCopy(false).title).toBe("選んだものだけ索引する");
  });

  it("lists indexing counts in a stable order", () => {
    expect(countRows({ COMPLETED: 2, QUEUED: 1, AUTO_INDEX_OFF: 0 }).map((row) => row.status)).toEqual([
      "QUEUED",
      "COMPLETED",
      "AUTO_INDEX_OFF",
    ]);
  });

  it("does not offer admin screens", () => {
    expect(showsAdminControls()).toBe(false);
    expect(SCREENS.map((screen) => screen.id)).toEqual(["overview", "settings"]);
  });

  it("keeps the previous flags when a toggle save fails, so a retry writes the same change", async () => {
    const current = { folders: "/data/a", includeSubfolders: true, autoIndex: true };
    const failed = await commitSettingsChange(current, { ...current, includeSubfolders: false }, async () => {
      throw new Error("保存に失敗しました");
    });
    expect(failed.value).toEqual(current);
    expect(failed.message).toBe("保存に失敗しました");

    const attempts: boolean[] = [];
    const again = await commitSettingsChange(failed.value, { ...failed.value, autoIndex: false }, async (next) => {
      attempts.push(next.autoIndex);
      throw new Error("down");
    });
    expect(attempts).toEqual([false]);
    expect(again.value.autoIndex).toBe(true);

    const saved = await commitSettingsChange(again.value, { ...again.value, includeSubfolders: false }, async (next) => next);
    expect(saved.value.includeSubfolders).toBe(false);
    expect(saved.message).toBe("保存しました");
  });

  it("sends the later toggle from the state the earlier save already changed", async () => {
    const saver = new SettingsSaver();
    let state = { folders: "/data/a", includeSubfolders: true, autoIndex: true };
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const bodies: Array<{ includeSubfolders: boolean; autoIndex: boolean }> = [];
    const first = saver.save(
      () => state,
      { includeSubfolders: false },
      async (draft) => {
        bodies.push({ includeSubfolders: draft.includeSubfolders, autoIndex: draft.autoIndex });
        await gate;
        state = { ...state, includeSubfolders: false };
        return { ...draft, folders: foldersText(parseFolders(draft.folders)) };
      },
      "includeSubfolders",
    );
    const second = saver.save(
      () => state,
      { autoIndex: false },
      async (draft) => {
        bodies.push({ includeSubfolders: draft.includeSubfolders, autoIndex: draft.autoIndex });
        state = { ...state, autoIndex: false };
        return { ...draft, folders: foldersText(parseFolders(draft.folders)) };
      },
      "autoIndex",
    );
    release();
    await first;
    await second;
    expect(bodies).toEqual([
      { includeSubfolders: false, autoIndex: true },
      { includeSubfolders: false, autoIndex: false },
    ]);
  });

  it("does not hand folder text back when a toggle save fails", async () => {
    const saver = new SettingsSaver();
    const result = await saver.save(
      () => ({ folders: "/typed-after-click", includeSubfolders: true, autoIndex: true }),
      { includeSubfolders: false },
      async () => {
        throw new Error("down");
      },
      "includeSubfolders",
    );
    expect(result.folders).toBeUndefined();
    expect(result.includeSubfolders).toBeUndefined();
    expect(result.message).toBe("down");
  });

  it("does not invent a failure sentence", () => {
    expect(failureLine(true, "索引の保存先に接続できません。復旧してから再試行してください。")).toContain("接続できません");
    expect(failureLine(false, null)).toBe("理由は分類できません。");
    expect(statusLabel("FAILED")).toBe("失敗");
    expect(statusLabel("UNKNOWN")).toBe("分類できない状態");
  });

  it("counts a folder from its own numbers and filters the table", () => {
    expect(folderSentence({ total: 4, completed: 4, active: 0, failed: 0, queued: 0 })).toBe("4件を取り込み済みです。");
    expect(folderSentence({ total: 3, completed: 1, active: 1, failed: 1, queued: 0 })).toContain("1件は取り込めませんでした");
    const rows = [
      { recordName: "議事録", indexingStatus: "COMPLETED" },
      { recordName: "予算", indexingStatus: "FAILED" },
    ];
    expect(visibleRecords(rows, "予算", false).map((row) => row.recordName)).toEqual(["予算"]);
    expect(visibleRecords(rows, "", true)).toEqual([rows[1]]);
  });
});
