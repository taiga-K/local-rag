import { describe, expect, it } from "vitest";
import { SCREENS, autoIndexCopy, commitSettingsChange, countRows, foldersText, parseFolders, showsAdminControls } from "./view";

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
    expect(SCREENS.map((screen) => screen.id)).toEqual(["folders", "index", "status"]);
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
});
