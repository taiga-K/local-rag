import { describe, expect, it } from "vitest";
import { customSeed, formatThreshold, thresholdCents, thresholdPartial, thresholdWarning } from "./threshold";

describe("custom threshold input", () => {
  it("accepts 0 to 1 with at most two decimal places", () => {
    expect(thresholdCents("0")).toBe(0);
    expect(thresholdCents("1")).toBe(100);
    expect(thresholdCents("0.8")).toBe(80);
    expect(thresholdCents("0.83")).toBe(83);
    expect(thresholdCents("0.90")).toBe(90);
    expect(thresholdCents("1.00")).toBe(100);
    expect(thresholdCents("0.836")).toBeNull();
    expect(thresholdCents("1.01")).toBeNull();
    expect(thresholdCents("-0.1")).toBeNull();
    expect(thresholdCents("2")).toBeNull();
  });

  it("treats a trailing dot as unfinished", () => {
    expect(thresholdPartial("0.")).toBe(true);
    expect(thresholdPartial("0.8")).toBe(false);
  });

  it("warns outside 0.80 to 0.86 and stays quiet inside", () => {
    expect(thresholdWarning(80)).toBe("");
    expect(thresholdWarning(83)).toBe("");
    expect(thresholdWarning(86)).toBe("");
    expect(thresholdWarning(79)).not.toBe("");
    expect(thresholdWarning(90)).toContain("目安の範囲外");
  });

  it("seeds custom from the previous level unless a custom value was saved", () => {
    expect(customSeed("off", null)).toBe("0.84");
    expect(customSeed("weak", null)).toBe("0.80");
    expect(customSeed("strong", null)).toBe("0.86");
    expect(customSeed("off", 0.9)).toBe("0.90");
  });

  it("formats a loaded number without a third decimal", () => {
    expect(formatThreshold(0.83)).toBe("0.83");
    expect(formatThreshold(0.9)).toBe("0.9");
    expect(formatThreshold(1)).toBe("1");
  });
});
