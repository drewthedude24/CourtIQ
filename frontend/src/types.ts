// The shapes the API sends back. They match backend/app.py and backend/database.py.

export type SessionStatus = "QUEUED" | "PROCESSING" | "COMPLETED" | "FAILED";

export type Shot = {
  shot_number: number;
  result: "MAKE" | "MISS";
  timestamp_s: number;
  reason: string | null;
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
