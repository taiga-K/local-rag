import { describe, expect, it } from "vitest";
import { folderPathKey } from "./bridge";

describe("folderPathKey", () => {
  it("ignores trailing path separators", () => {
    expect(folderPathKey("/data/notes/")).toBe("/data/notes");
    expect(folderPathKey("/data/notes//")).toBe("/data/notes");
    expect(folderPathKey("C:\\data\\notes\\")).toBe("C:\\data\\notes");
  });

  it("keeps root paths valid", () => {
    expect(folderPathKey("/")).toBe("/");
    expect(folderPathKey("C:\\")).toBe("C:\\");
    expect(folderPathKey("C:/")).toBe("C:/");
  });

  it("does not trim whitespace", () => {
    expect(folderPathKey("/data/report ")).toBe("/data/report ");
  });
});
