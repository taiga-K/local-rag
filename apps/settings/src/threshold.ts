export const THRESHOLD_HINT = "目安: 0.80〜0.86。高いほど結果が減ります。";
export const THRESHOLD_WARN =
  "目安の範囲外です。0.75未満ではほとんど除かれず、0.86を超えると関係のある文書も多く除かれます。";
export const THRESHOLD_ERROR = "0から1まで、小数第2位までの数値を入れてください。";

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
