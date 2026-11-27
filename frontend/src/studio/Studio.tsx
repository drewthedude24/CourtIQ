import { useEffect, useState, type ChangeEvent } from "react";
import FormTable from "../FormTable";
import FormTrend from "../FormTrend";
import Login from "../Login";
import SessionsTable from "../SessionsTable";
import { formatDate } from "../format";
import type { FormTrendRow, Session, SessionStatus, SessionSummary, Shot } from "../types";
import { uploadVideo } from "../upload";
import Analysis from "./Analysis";
import MlTab from "./MlTab";
import ProgressChart from "./ProgressChart";
import logo from "./courtiq-logo.webp";

// The Studio page: the same data as the original page at /, laid out as tabs beside a sidebar.

const PENDING_STATUSES = new Set<SessionStatus>(["QUEUED", "PROCESSING"]);

// `short` is the label on a phone, where all five tabs share one row.
const TABS = [
  { id: "dashboard", label: "Dashboard", short: "Dashboard" },
  { id: "sessions", label: "Sessions", short: "Sessions" },
  { id: "shots", label: "Shot review", short: "Shots" },
  { id: "progress", label: "Progress", short: "Progress" },
  { id: "ml", label: "ML", short: "ML" },
] as const;
type Tab = (typeof TABS)[number]["id"];

// The tab lives in the address (#progress), so a refresh or the back button keeps your place.
function tabFromHash(): Tab {
  const id = window.location.hash.slice(1);
  return TABS.some((tab) => tab.id === id) ? (id as Tab) : "dashboard";
}

export default function Studio() {
  // The logged-in email, null when logged out, undefined until the server has answered.
  const [account, setAccount] = useState<string | null | undefined>(undefined);
  const [tab, setTab] = useState<Tab>(tabFromHash);
  const [history, setHistory] = useState<SessionSummary[]>([]);
  const [formTrend, setFormTrend] = useState<FormTrendRow[]>([]);
  // The open session, shown on the dashboard.
  const [session, setSession] = useState<Session | null>(null);
  const [upload, setUpload] = useState<{ name: string; sent: number; total: number } | null>(null);
  const [failed, setFailed] = useState(false);
  // A shot to play, picked on the Shot review tab. `at` makes picking the same shot twice count.
  const [request, setRequest] = useState<{ sessionId: string; shot: Shot; at: number } | null>(null);

  useEffect(() => {
    fetch("/api/me")
      .then((response) => (response.ok ? response.json() : null))
      .then((me) => setAccount(me ? me.email : null))
      .catch(() => setAccount(null));
  }, []);

  useEffect(() => {
    const onHash = () => setTab(tabFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // Reads one API answer. A 401 means the login has ended, so the login page shows again.
  async function load<T>(url: string): Promise<T | null> {
    const response = await fetch(url);
    if (response.status === 401) setAccount(null);
    return response.ok ? response.json() : null;
  }

  async function loadTables() {
    const [sessions, trend] = await Promise.all([
      load<SessionSummary[]>("/api/sessions"),
      load<FormTrendRow[]>("/api/stats/form"),
    ]);
    if (sessions) setHistory(sessions);
    if (trend) setFormTrend(trend);
    return sessions;
  }

  // Once logged in, load everything and open the newest finished session.
  useEffect(() => {
    if (!account) return;
    loadTables().then((sessions) => {
      const newest = sessions?.find((row) => row.status === "COMPLETED");
      if (newest) openSession(newest.id);
    });
  }, [account]);

  // While the open session is being processed, ask the server about it every second.
  useEffect(() => {
    if (!session || !PENDING_STATUSES.has(session.status)) return undefined;
    const timer = window.setTimeout(async () => {
      const next = await openSession(session.id);
      // It just finished, so reload the lists to show its numbers everywhere.
      if (next && !PENDING_STATUSES.has(next.status)) loadTables();
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [session]);

  async function openSession(id: string): Promise<Session | null> {
    try {
      const response = await fetch(`/api/sessions/${id}`);
      if (!response.ok) throw new Error("Session request failed");
      const next: Session = await response.json();
      setSession(next);
      setFailed(false);
      return next;
    } catch {
      setFailed(true);
      return null;
    }
  }

  async function selectVideo(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    go("dashboard");
    setUpload({ name: file.name, sent: 0, total: file.size });
    setFailed(false);
    setSession(null);
    try {
      setSession(await uploadVideo(file, (sent, total) => setUpload({ name: file.name, sent, total })));
      loadTables(); // The new session shows in the list as "Waiting".
    } catch {
      setFailed(true);
    } finally {
      setUpload(null);
    }
  }

  async function deleteSession(row: SessionSummary) {
    if (!window.confirm(`Delete ${row.original_filename} and its video? This can't be undone.`)) return;
    const response = await fetch(`/api/sessions/${row.id}`, { method: "DELETE" });
    if (!response.ok) return setFailed(true);
    if (session?.id === row.id) setSession(null);
    loadTables();
  }

  function go(next: Tab) {
    window.location.hash = next === "dashboard" ? "" : next;
    setTab(next);
  }

  function pickSession(id: string) {
    openSession(id);
    go("dashboard");
  }

  function playShot(shot: Shot) {
    if (session) setRequest({ sessionId: session.id, shot, at: Date.now() });
    go("dashboard");
  }

  async function logOut() {
    await fetch("/api/logout", { method: "POST" });
    window.location.reload(); // A fresh page drops everything the last account loaded.
  }

  const working = upload !== null || (session !== null && PENDING_STATUSES.has(session.status));

  // The real file input is hidden and the label opens it.
  const uploadButton = (
    <label className={working ? "button disabled" : "button"}>
      <UploadIcon />
      Upload clip
      <input type="file" accept="video/mp4,video/quicktime,.mov,.mp4,.m4v" onChange={selectVideo} disabled={working} />
    </label>
  );

  if (account === undefined) return null; // Asking the server, which takes a moment.

  if (account === null) {
    return (
      <div className="signed-out">
        <img className="logo" src={logo} alt="CourtIQ" width={320} height={100} />
        <Login onLoggedIn={setAccount} />
        <Credit />
      </div>
    );
  }

  return (
    <div className="studio">
      <aside className="sidebar">
        <a className="brand" href="/studio/" aria-label="CourtIQ Studio, dashboard">
          <img className="logo" src={logo} alt="CourtIQ" width={320} height={100} />
        </a>
        <nav aria-label="Studio">
          {TABS.map((item) => (
            <a
              key={item.id}
              href={item.id === "dashboard" ? "#" : `#${item.id}`}
              aria-current={tab === item.id ? "page" : undefined}
              onClick={(event) => {
                event.preventDefault();
                go(item.id);
              }}
            >
              <span className="tab-long">{item.label}</span>
              <span className="tab-short">{item.short}</span>
            </a>
          ))}
        </nav>
        {/* The gear from the sketch: opens the account, the one setting there is. */}
        <details className="account">
          <summary aria-label="Account">
            <GearIcon />
            <span title={account}>{account}</span>
          </summary>
          <div className="account-menu">
            <span className="account-email">{account}</span>
            <button className="text-button" type="button" onClick={logOut}>Log out</button>
          </div>
        </details>
      </aside>

      <main>
        {tab === "dashboard" && (
          <>
            <header className="page-head">
              <h1>Session analysis</h1>
              <div className="page-actions">
                {history.length > 0 && (
                  <select
                    aria-label="Session"
                    value={session?.id ?? ""}
                    disabled={working}
                    onChange={(event) => openSession(event.target.value)}
                  >
                    {!session && <option value="">Pick a session</option>}
                    {history.map((row, index) => (
                      <option key={row.id} value={row.id}>
                        Session {history.length - index} · {row.original_filename} · {formatDate(row.created_at)}
                      </option>
                    ))}
                  </select>
                )}
                {uploadButton}
              </div>
            </header>
            <Analysis session={session} upload={upload} failed={failed} request={request} hasHistory={history.length > 0} />
            {history.length > 1 && (
              <section className="block">
                <h2>Progress</h2>
                <ProgressChart sessions={history} openId={session?.id} onOpen={openSession} />
              </section>
            )}
          </>
        )}

        {tab === "sessions" && (
          <>
            <header className="page-head">
              <h1>Sessions</h1>
              <div className="page-actions">{uploadButton}</div>
            </header>
            <SessionsTable
              sessions={history}
              selectedId={session?.id}
              disabled={working}
              onSelect={pickSession}
              onDelete={deleteSession}
            />
          </>
        )}

        {tab === "shots" && (
          <>
            <header className="page-head">
              <h1>Shot review</h1>
              {session && <p className="detail">{session.original_filename} · {formatDate(session.created_at)}</p>}
            </header>
            {session?.status === "COMPLETED" ? (
              <FormTable
                session={session}
                onJump={playShot}
                picked={request?.sessionId === session.id ? request.shot.shot_number : null}
              />
            ) : (
              <p className="detail">Open a finished session on the Dashboard to see every shot here.</p>
            )}
          </>
        )}

        {tab === "progress" && (
          <>
            <header className="page-head">
              <h1>Progress</h1>
            </header>
            {history.length > 0 ? (
              <section className="block">
                <h2>Field goal % by session</h2>
                <ProgressChart sessions={history} openId={session?.id} onOpen={pickSession} />
              </section>
            ) : (
              <p className="detail">Upload a clip to start tracking your progress.</p>
            )}
            <FormTrend rows={formTrend} />
          </>
        )}

        {tab === "ml" && <MlTab />}
      </main>
    </div>
  );
}

function GearIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="3.2" />
      <path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1" />
      <circle cx="12" cy="12" r="6.5" />
    </svg>
  );
}

function UploadIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <path d="M8 11V2.5M4.5 6 8 2.5 11.5 6M2.5 13.5h11" />
    </svg>
  );
}

// The login panel shows the original page's photo, whose licence (CC BY-SA 4.0) asks for the
// photographer's name, a link, and a note that the picture was changed.
function Credit() {
  return (
    <footer className="credit">
      Photo of Breanna Stewart by{" "}
      <a href="https://commons.wikimedia.org/wiki/File:260927_Lynx_Liberty_JohnMc90_(55555504475).jpg">John McClellan</a>,{" "}
      <a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</a>, cropped.
    </footer>
  );
}
