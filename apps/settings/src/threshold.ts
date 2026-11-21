import type { ThresholdLevel } from "./api";

export const THRESHOLD_ROW_NAME = "関係の薄い文書を除く";
export const THRESHOLD_ROW_DESC = "質問と似ていない文書を検索結果から外します。";
export const THRESHOLD_LABEL = "しきい値";
export const THRESHOLD_HINT = "目安: 0.80〜0.86。高いほど結果が減ります。";
export const THRESHOLD_WARN =
  "目安の範囲外です。0.75未満ではほとんど除かれず、0.86を超えると関係のある文書も多く除かれます。";
export const THRESHOLD_ERROR = "0から1まで、小数第2位までの数値を入れてください。";

export const THRESHOLD_OPTIONS: { id: ThresholdLevel; label: string; number?: string }[] = [
  { id: "off", label: "除かない" },
  { id: "weak", label: "弱く", number: "0.80" },
  { id: "standard", label: "標準", number: "0.84" },
  { id: "strong", label: "強く", number: "0.86" },
  { id: "custom", label: "カスタム" },
];

const GUIDE_LOW = 80;
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
