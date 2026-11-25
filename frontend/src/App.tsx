import { useEffect, useState, type ChangeEvent } from "react";
import FormTrend from "./FormTrend";
import SessionsTable from "./SessionsTable";
import StatsPanel from "./StatsPanel";
import { formatPct } from "./format";
import type { FormTrendRow, Session, SessionStatus, SessionSummary, Stats } from "./types";
import Viewer from "./Viewer";

const PENDING_STATUSES = new Set<SessionStatus>(["QUEUED", "PROCESSING"]);

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [uploading, setUploading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [history, setHistory] = useState<SessionSummary[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [formTrend, setFormTrend] = useState<FormTrendRow[]>([]);

  function loadTables() {
    fetch("/api/sessions").then((response) => response.json()).then(setHistory);
    fetch("/api/stats").then((response) => response.json()).then(setStats);
    fetch("/api/stats/form").then((response) => response.json()).then(setFormTrend);
  }

  // Load the sessions list and stats when the page opens, and again whenever the
  // current upload changes status (so a finished upload shows up in both tables).
  useEffect(() => {
    loadTables();
  }, [session?.status]);

  useEffect(() => {
    if (!session || !PENDING_STATUSES.has(session.status)) return undefined;

    const sessionId = session.id;
    let cancelled = false;
    let timer: number | undefined;

    async function refreshSession() {
      try {
        const response = await fetch(`/api/sessions/${sessionId}`);
        if (!response.ok) throw new Error("Status request failed");

        const updatedSession: Session = await response.json();
        if (cancelled) return;

        setSession(updatedSession);
        setFailed(updatedSession.status === "FAILED");
        if (PENDING_STATUSES.has(updatedSession.status)) {
          timer = window.setTimeout(refreshSession, 2000);
        }
      } catch {
        if (!cancelled) setFailed(true);
      }
    }

    timer = window.setTimeout(refreshSession, 1000);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [session]);

  async function selectVideo(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    setUploading(true);
    setFailed(false);
    setSession(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch("/api/sessions", {
        method: "POST",
        body: formData,
      });
      if (!response.ok) throw new Error("Upload failed");
      setSession(await response.json());
    } catch {
      setFailed(true);
    } finally {
      setUploading(false);
    }
  }

  // A past session from the table. It goes into the same `session` state an upload uses,
  // so the viewer shows it exactly like a fresh upload.
  async function selectSession(id: string) {
    setFailed(false);
    try {
      const response = await fetch(`/api/sessions/${id}`);
      if (!response.ok) throw new Error("Session request failed");
      setSession(await response.json());
    } catch {
      setFailed(true);
    }
  }

  async function deleteSession(row: SessionSummary) {
    const ok = window.confirm(
      `Delete ${row.original_filename} and its video? This can't be undone.`,
    );
    if (!ok) return;

    setFailed(false);
    try {
      const response = await fetch(`/api/sessions/${row.id}`, { method: "DELETE" });
      if (!response.ok) throw new Error("Delete request failed");
      if (session?.id === row.id) setSession(null); // close it if it was open
      loadTables();
    } catch {
      setFailed(true);
    }
  }

  const working = uploading || (session !== null && PENDING_STATUSES.has(session.status));

  return (
    <>
      <header>
        <div>
          <h1>CourtIQ</h1>
          <p className="detail">Upload a shooting clip. See every make and miss, and how your form held up.</p>
        </div>
        <label className={working ? "button disabled" : "button"}>
          Upload video
          <input
            type="file"
            accept="video/mp4,video/quicktime,.mov,.mp4,.m4v"
            onChange={selectVideo}
            disabled={working}
          />
        </label>
      </header>

      <main>
        {/* Everything uploaded so far, in four numbers. */}
        {stats && history.length > 0 && (
          <dl className="totals">
            <div><dt>Sessions</dt><dd>{history.length}</dd></div>
            <div><dt>Shots</dt><dd>{stats.overall.makes + stats.overall.misses}</dd></div>
            <div><dt>Made</dt><dd>{stats.overall.makes}</dd></div>
            <div><dt>Shooting</dt><dd>{formatPct(stats.overall.shooting_pct)}</dd></div>
          </dl>
        )}
        <Viewer session={session} uploading={uploading} failed={failed} />
        <div className="tables">
          <SessionsTable
            sessions={history}
            selectedId={session?.id}
            disabled={working}
            onSelect={selectSession}
            onDelete={deleteSession}
          />
          <StatsPanel stats={stats} />
          <FormTrend rows={formTrend} />
        </div>
      </main>
    </>
  );
}
