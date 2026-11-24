// Small display helpers shared by the components.

import type { FormNumbers } from "./types";

// The form numbers in the order the tables show them, and how to print each one.
export const FORM_COLUMNS: { key: keyof FormNumbers; label: string; digits: number; unit: string }[] = [
  { key: "knee_bend_deg", label: "Knee", digits: 0, unit: "°" },
  { key: "elbow_bend_deg", label: "Elbow", digits: 0, unit: "°" },
  { key: "arm_angle_deg", label: "Arm", digits: 0, unit: "°" },
  { key: "jump", label: "Jump", digits: 2, unit: "" },
  { key: "flight_time_s", label: "Flight", digits: 2, unit: " s" },
];

// 94.8 with 0 digits and "°" -> "95°". A number that was not measured -> "-".
export function formatNumber(value: number | null, digits: number, unit: string) {
  return value === null ? "-" : value.toFixed(digits) + unit;
}

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
