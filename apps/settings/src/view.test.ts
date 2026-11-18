import { describe, expect, it } from "vitest";
import { SCREENS, autoIndexCopy, countRows, foldersText, parseFolders, showsAdminControls } from "./view";

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
});
