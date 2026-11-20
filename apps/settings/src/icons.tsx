const PATHS = {
  home: "M2.5 7.5 8 3l5.5 4.5V13a.5.5 0 0 1-.5.5H10v-4H6v4H3a.5.5 0 0 1-.5-.5z",
  folder: "M1.5 4a1 1 0 0 1 1-1h3.6l1.5 1.5h5.9a1 1 0 0 1 1 1V12a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1z",
  plus: "M8 3v10M3 8h10",
  gear: "M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4",
  err: "M8 4.75v3.75M8 10.75v.5",
  pause: "M6 4v8M10 4v8",
  search: "M7 7m-4 0a4 4 0 1 0 8 0a4 4 0 1 0-8 0M10 10l3.5 3.5",
  info: "M8 7.25v4M8 4.75v.5",
  chev: "m4 6 4 4 4-4",
  check: "m5.5 8 1.75 1.75L10.5 6.5",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 16 }: { name: IconName; size?: number }) {
  const circle = name === "err" || name === "info" || name === "check" || name === "gear";
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 16 16" aria-hidden="true">
      {circle ? <circle cx="8" cy="8" r={name === "gear" ? 5.25 : 6} /> : null}
      <path d={PATHS[name]} />
    </svg>
  );
}
