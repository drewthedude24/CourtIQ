import { useEffect, useState, type ChangeEvent } from "react";
import Fatigue from "./Fatigue";
import FormTrend from "./FormTrend";
import Login from "./Login";
import SessionsTable from "./SessionsTable";
import StatsPanel from "./StatsPanel";
import { formatPct } from "./format";
import type { FatigueReport, FormTrendRow, Session, SessionStatus, SessionSummary, Stats } from "./types";
import { uploadVideo } from "./upload";
import Viewer from "./Viewer";

const PENDING_STATUSES = new Set<SessionStatus>(["QUEUED", "PROCESSING"]);

export default function App() {
  // The logged-in email, null when logged out, undefined until the server has answered.
  const [account, setAccount] = useState<string | null | undefined>(undefined);
  const [session, setSession] = useState<Session | null>(null);
  // The file being sent, and how many of its bytes have gone out. null when nothing is uploading.
  const [upload, setUpload] = useState<{ name: string; sent: number; total: number } | null>(null);
  const [failed, setFailed] = useState(false);
  const [history, setHistory] = useState<SessionSummary[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [formTrend, setFormTrend] = useState<FormTrendRow[]>([]);
  const [fatigue, setFatigue] = useState<FatigueReport | null>(null);

  // Is this browser logged in? The login cookie can't be read by the page, so ask the server.
  useEffect(() => {
    fetch("/api/me")
      .then((response) => (response.ok ? response.json() : null))
      .then((me) => setAccount(me ? me.email : null))
      .catch(() => setAccount(null));
  }, []);

  // Reads one API answer into state. A 401 means the login has ended (logged out in another
  // tab, or 30 days passed), so the login page shows again.
  async function load<T>(url: string, set: (value: T) => void) {
    const response = await fetch(url);
    if (response.status === 401) setAccount(null);
    else if (response.ok) set(await response.json());
  }

  function loadTables() {
    load("/api/sessions", setHistory);
    load("/api/stats", setStats);
    load("/api/stats/form", setFormTrend);
    load("/api/stats/fatigue", setFatigue);
  }

  // Load the sessions list and stats once logged in, and again whenever the
  // current upload changes status (so a finished upload shows up in both tables).
  useEffect(() => {
    if (account) loadTables();
  }, [account, session?.status]);

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
          timer = window.setTimeout(refreshSession, 1000);
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

    setUpload({ name: file.name, sent: 0, total: file.size });
    setFailed(false);
    setSession(null);

    try {
      setSession(await uploadVideo(file, (sent, total) => setUpload({ name: file.name, sent, total })));
    } catch {
      setFailed(true);
    } finally {
      setUpload(null);
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

  function loggedIn(email: string) {
    setSession(null); // Never keep a session open from whoever was logged in before.
    setAccount(email);
  }

  async function logOut() {
    await fetch("/api/logout", { method: "POST" });
    // A fresh page drops everything the last account had loaded.
    window.location.reload();
  }

  const working = upload !== null || (session !== null && PENDING_STATUSES.has(session.status));

  // The upload button. The real file input is hidden and the label opens it.
  const uploadButton = (text: string) => (
    <label className={working ? "button disabled" : "button"}>
      {text}
      <input
        type="file"
        accept="video/mp4,video/quicktime,.mov,.mp4,.m4v"
        onChange={selectVideo}
        disabled={working}
      />
    </label>
  );

  if (account === undefined) return null; // Asking the server, which takes a moment.

  if (account === null) {
    return (
      <>
        <header>
          <a className="brand" href="/" aria-label="CourtIQ, home">
            <Mark />
            <h1>Court<b>IQ</b></h1>
          </a>
        </header>
        <main>
          <Login onLoggedIn={loggedIn} />
        </main>
        <Credit />
      </>
    );
  }

  return (
    <>
      <header>
        <a className="brand" href="/" aria-label="CourtIQ, home">
          <Mark />
          <h1>Court<b>IQ</b></h1>
        </a>
        {history.length > 0 && (
          <nav aria-label="Sections">
            <a href="#sessions">Sessions</a>
            <a href="#months">By month</a>
            <a href="#trend">Form over time</a>
            <a href="#fatigue">Fatigue</a>
          </nav>
        )}
        <span className="account">
          {account}
          <button className="text-button" type="button" onClick={logOut}>Log out</button>
        </span>
        {uploadButton("Upload video")}
      </header>

      <main>
        <Viewer
          session={session}
          upload={upload}
          failed={failed}
          hasHistory={history.length > 0}
          uploadButton={uploadButton("Choose a video")}
        />
        <div className="tables">
          {/* Everything uploaded so far, in one line. */}
          {stats && history.length > 0 && (
            <p className="totals">
              <span><b>{history.length}</b> {history.length === 1 ? "session" : "sessions"}</span>
              <span><b>{stats.overall.makes + stats.overall.misses}</b> shots</span>
              <span><b>{stats.overall.makes}</b> made</span>
              <span><b>{formatPct(stats.overall.shooting_pct)}</b> shooting</span>
            </p>
          )}
          <SessionsTable
            sessions={history}
            selectedId={session?.id}
            disabled={working}
            onSelect={selectSession}
            onDelete={deleteSession}
          />
          <StatsPanel stats={stats} />
          <FormTrend rows={formTrend} />
          <Fatigue report={fatigue} />
        </div>
      </main>

      <Credit />
    </>
  );
}

// The photo's licence (CC BY-SA 4.0) asks for the photographer's name, a link, and a note
// that the picture was changed. Both the welcome and the login panel show the photo.
function Credit() {
  return (
    <footer>
      Photo of Breanna Stewart by{" "}
      <a href="https://commons.wikimedia.org/wiki/File:260927_Lynx_Liberty_JohnMc90_(55555504475).jpg">John McClellan</a>,{" "}
      <a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</a>, cropped.
    </footer>
  );
}

// The CourtIQ mark: a basketball inside tracking brackets, and the dotted path the tracker
// draws behind it.
function Mark() {
  return (
    <svg className="logo" viewBox="0 0 46 34" aria-hidden="true">
      <path className="logo-brackets" d="M1 12 V7 H6 M24 7 H29 V12 M29 28 V33 H24 M6 33 H1 V28" />
      <circle className="logo-ball" cx="15" cy="20" r="10" />
      <path className="logo-seam" d="M5 20 H25 M15 10 V30 M8 13 Q15 20 8 27 M22 13 Q15 20 22 27" />
      <path className="logo-path" d="M30 9 Q36 3 43 2" />
    </svg>
  );
}
