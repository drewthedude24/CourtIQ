// Small display helpers shared by the components.

export function formatPct(pct: number | null) {
  return pct === null ? "-" : `${pct}%`;
}

// "2026-11-22T07:56:05+00:00" -> "Nov 22"
export function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// 45.6 -> "0:46"
export function formatTime(seconds: number) {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}
