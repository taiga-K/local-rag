import { describe, expect, it } from "vitest";
import {
  commitThresholdText,
  customSeed,
  formatThreshold,
  persistThresholdLevel,
  stepThresholdCents,
  thresholdCents,
  thresholdPartial,
  thresholdWarning,
} from "./threshold";

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

  it("warns below 0.75 or above 0.86 and stays quiet inside", () => {
    expect(thresholdWarning(75)).toBe("");
    expect(thresholdWarning(80)).toBe("");
    expect(thresholdWarning(83)).toBe("");
    expect(thresholdWarning(86)).toBe("");
    expect(thresholdWarning(74)).not.toBe("");
    expect(thresholdWarning(87)).not.toBe("");
    expect(thresholdWarning(90)).toContain("目安の範囲外");
  });

  it("normalizes, rounds half-up, and rejects values outside 0 to 1", () => {
    expect(commitThresholdText(" ０．８３ ")).toEqual({ ok: true, cents: 83, text: "0.83" });
    expect(commitThresholdText(".83")).toEqual({ ok: true, cents: 83, text: "0.83" });
    expect(commitThresholdText("0.835")).toEqual({ ok: true, cents: 84, text: "0.84" });
    expect(commitThresholdText("0.834")).toEqual({ ok: true, cents: 83, text: "0.83" });
    expect(commitThresholdText("0.995")).toEqual({ ok: true, cents: 100, text: "1.00" });
    expect(commitThresholdText("1.005").ok).toBe(false);
    expect(commitThresholdText("abc").ok).toBe(false);
    expect(commitThresholdText("2").ok).toBe(false);
    expect(commitThresholdText("-0.1").ok).toBe(false);
  });

  it("steps by one hundredth and clamps to 0 and 1", () => {
    expect(stepThresholdCents(83, 1)).toBe(84);
    expect(stepThresholdCents(83, -1)).toBe(82);
    expect(stepThresholdCents(0, -1)).toBe(0);
    expect(stepThresholdCents(100, 1)).toBe(100);
  });

  it("keeps custom selected when the number matches a named tier", () => {
    expect(persistThresholdLevel("custom", 84)).toBe("custom");
    expect(persistThresholdLevel("custom", 80)).toBe("custom");
    expect(persistThresholdLevel("standard", 84)).toBe("standard");
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
