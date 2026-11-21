import type { ThresholdLevel } from "./api";

export const THRESHOLD_ROW_NAME = "関係の薄い文書を除く";
export const THRESHOLD_ROW_DESC = "質問と似ていない文書を検索結果から外します。";
export const THRESHOLD_HINT = "目安: 0.80〜0.86。高いほど結果が減ります。";
export const THRESHOLD_WARN =
  "目安の範囲外です。0.75未満ではほとんど除かれず、0.86を超えると関係のある文書も多く除かれます。";
export const THRESHOLD_ERROR = "0から1まで、小数第2位までの数値を入れてください。";
export const THRESHOLD_OFF_VALUE = "―";

export const THRESHOLD_SEGMENTS: { id: ThresholdLevel; label: string }[] = [
  { id: "off", label: "除かない" },
  { id: "weak", label: "弱く" },
  { id: "standard", label: "標準" },
  { id: "strong", label: "強く" },
  { id: "custom", label: "カスタム" },
];

const GUIDE_LOW = 75;
const GUIDE_HIGH = 86;

export function thresholdCents(text: string): number | null {
  if (!/^(?:1(?:\.0{1,2})?|0(?:\.\d{1,2})?)$/.test(text)) {
    return null;
  }
  const [whole, frac = ""] = text.split(".");
  const padded = `${frac}00`.slice(0, 2);
  return Number(whole) * 100 + Number(padded);
}

export function thresholdPartial(text: string): boolean {
  return text === "0." || text === "1.";
}

export function thresholdWarning(cents: number): string {
  if (cents < GUIDE_LOW || cents > GUIDE_HIGH) {
    return THRESHOLD_WARN;
  }
  return "";
}

const LEVEL_SEED = { off: 0.84, weak: 0.8, standard: 0.84, strong: 0.86 } as const;

export function customSeed(previous: keyof typeof LEVEL_SEED, saved: number | null): string {
  const value = saved ?? LEVEL_SEED[previous];
  return (Math.round(value * 100) / 100).toFixed(2);
}

export type ThresholdCommit =
  | { ok: true; cents: number; text: string }
  | { ok: false };

export function normalizeThresholdText(raw: string): string {
  const folded = raw.trim().replace(/[０-９]/g, (digit) => String.fromCharCode(digit.charCodeAt(0) - 0xfee0)).replace(/[．。]/g, ".");
  if (folded.startsWith(".")) {
    return `0${folded}`;
  }
  return folded;
}

export function thresholdDraftIncomplete(raw: string): boolean {
  const normalized = normalizeThresholdText(raw);
  return normalized === "" || normalized.endsWith(".");
}

export function commitThresholdText(raw: string): ThresholdCommit {
  const normalized = normalizeThresholdText(raw);
  if (normalized.endsWith(".")) {
    return { ok: false };
  }
  const match = /^(\d+)(?:\.(\d+))?$/.exec(normalized);
  if (!match) {
    return { ok: false };
  }
  const whole = Number(match[1]);
  if (!Number.isSafeInteger(whole)) {
    return { ok: false };
  }
  const fraction = match[2] ?? "";
  const hundredths = Number((fraction + "00").slice(0, 2));
  const third = fraction.length >= 3 ? Number(fraction[2]) : 0;
  let cents = whole * 100 + hundredths;
  if (third >= 5) {
    cents += 1;
  }
  if (cents < 0 || cents > 100) {
    return { ok: false };
  }
  return { ok: true, cents, text: (cents / 100).toFixed(2) };
}

export function stepThresholdCents(cents: number, direction: -1 | 1): number {
  const next = cents + direction;
  if (next < 0) {
    return 0;
  }
  if (next > 100) {
    return 100;
  }
  return next;
}

export function persistThresholdLevel(level: ThresholdLevel, _cents: number | null): ThresholdLevel {
  return level;
}

export function tierBoxText(level: Exclude<ThresholdLevel, "custom">): string {
  switch (level) {
    case "off":
      return THRESHOLD_OFF_VALUE;
    case "weak":
      return "0.80";
    case "standard":
      return "0.84";
    case "strong":
      return "0.86";
    default: {
      const unexpected: never = level;
      return unexpected;
    }
  }
}

export function formatThreshold(value: number): string {
  const cents = Math.round(value * 100);
  const whole = Math.trunc(cents / 100);
  const frac = Math.abs(cents % 100);
  if (frac === 0) {
    return String(whole);
  }
  if (frac % 10 === 0) {
    return `${whole}.${frac / 10}`;
  }
  return `${whole}.${String(frac).padStart(2, "0")}`;
}
