// The shapes the API sends back. They match backend/app.py and backend/database.py.

export type SessionStatus = "QUEUED" | "PROCESSING" | "COMPLETED" | "FAILED";

// The shooter's form on a shot (vision/shot_form.py). null when it could not be measured.
export type FormNumbers = {
  knee_bend_deg: number | null;
  elbow_bend_deg: number | null;
  arm_angle_deg: number | null;
  jump: number | null;
  flight_time_s: number | null;
};

export type Shot = FormNumbers & {
  shot_number: number;
  result: "MAKE" | "MISS";
  timestamp_s: number;
  reason: string | null;
};

// The average of each form number over a group of shots, and its spread: how much it
// changes from shot to shot (the standard deviation). Spread needs at least two shots.
// `shots` is how many shots are in the group, and `..._shots` how many of them that
// number was measured on.
export type FormSummary = FormNumbers & {
  shots: number;
  knee_bend_deg_shots: number;
  elbow_bend_deg_shots: number;
  arm_angle_deg_shots: number;
  jump_shots: number;
  flight_time_s_shots: number;
  knee_bend_deg_spread: number | null;
  elbow_bend_deg_spread: number | null;
  arm_angle_deg_spread: number | null;
  jump_spread: number | null;
  flight_time_s_spread: number | null;
};

// GET /api/sessions/{id}
export type Session = {
  id: string;
  original_filename: string;
  status: SessionStatus;
  makes: number;
  misses: number;
  created_at: string;
  completed_at: string | null;
  error_message: string | null;
  video_url: string | null;
  shots: Shot[];
  // makes or misses is null when the session has none.
  form: { makes: FormSummary | null; misses: FormSummary | null; all: FormSummary };
};

// One row of GET /api/stats/form: a session's average form numbers and their spread.
export type FormTrendRow = FormSummary & {
  shooting_pct: number;
  id: string;
  original_filename: string;
  created_at: string;
};

// One row of GET /api/sessions. shooting_pct is null when a session has no shots.
export type SessionSummary = {
  id: string;
  original_filename: string;
  status: SessionStatus;
  created_at: string;
  makes: number;
  misses: number;
  shooting_pct: number | null;
};

export type ShotTotals = {
  makes: number;
  misses: number;
  shooting_pct: number | null;
};

// GET /api/stats. month looks like "2026-11-01".
export type Stats = {
  overall: ShotTotals;
  months: (ShotTotals & { month: string })[];
};
