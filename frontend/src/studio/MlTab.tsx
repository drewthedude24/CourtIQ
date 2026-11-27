import { useEffect, useState } from "react";
import { formatDate } from "../format";

// GET /api/stats/fatigue (backend/fatigue.py, being built on the feat/fatigue-ml branch).
// Only the fields this tab shows are listed.
type Fatigue = {
  model: {
    sessions: number;
    dropped: number;
    typical_shots: number;
    drop_pct: number;
    check: { with_trend: number; without: number };
  } | null;
  sessions: { id: string; original_filename: string; created_at: string; first: number; last: number }[];
  makes: { early: { makes: number; shots: number }; late: { makes: number; shots: number }; clear: boolean } | null;
};

// The ML tab: a small model of how your jump changes through a session.
export default function MlTab() {
  // undefined while loading, null when the server doesn't have the model yet.
  const [report, setReport] = useState<Fatigue | null | undefined>(undefined);
  useEffect(() => {
    fetch("/api/stats/fatigue")
      .then((response) => (response.ok ? response.json() : null))
      .then(setReport)
      .catch(() => setReport(null));
  }, []);

  return (
    <>
      <header className="page-head">
        <h1>ML: jump through a session</h1>
      </header>
      <p className="lead">
        Jump is the one form number that falls as a session goes on. This model learns how much it
        drops per shot from all your sessions, and checks that on sessions it never saw.
      </p>
      {report === null && (
        <section className="notice">
          <h2>Coming soon</h2>
          <p>The jump model is still being built. It will show here once it is on the server.</p>
        </section>
      )}
      {report && !report.model && (
        <section className="notice">
          <h2>Not enough sessions yet</h2>
          <p className="detail">The model needs at least 3 sessions with 5 or more measured jumps each.</p>
        </section>
      )}
      {report?.model && (
        <>
          <dl className="scoreboard">
            <div>
              <dt>Jump drop, first to last shot</dt>
              <dd>{Math.abs(report.model.drop_pct).toFixed(1)}%</dd>
            </div>
            <div>
              <dt>Sessions that ended lower</dt>
              <dd>{report.model.dropped}<small> of {report.model.sessions}</small></dd>
            </div>
            <div>
              <dt>Error with the trend</dt>
              <dd>{report.model.check.with_trend.toFixed(3)}</dd>
            </div>
            <div>
              <dt>Error without it</dt>
              <dd>{report.model.check.without.toFixed(3)}</dd>
            </div>
          </dl>
          <p className="detail caption">
            Over a typical {report.model.typical_shots}-shot session. The two errors are how far off the
            guessed jump was, in shoulder-heights, on each session when the model learned only from the
            others. A smaller error with the trend means the drop carries over to new sessions.
          </p>
          <section className="block">
            <h2>Each session</h2>
            <table>
              <thead>
                <tr>
                  <th>Clip</th>
                  <th className="wide-only">Date</th>
                  <th className="num">First 3 jumps</th>
                  <th className="num">Last 3 jumps</th>
                  <th className="num">Change</th>
                </tr>
              </thead>
              <tbody>
                {report.sessions.map((row) => (
                  <tr key={row.id}>
                    <td className="clip">{row.original_filename}</td>
                    <td className="wide-only">{formatDate(row.created_at)}</td>
                    <td className="num">{row.first.toFixed(2)}</td>
                    <td className="num">{row.last.toFixed(2)}</td>
                    <td className="num">{(row.last - row.first >= 0 ? "+" : "") + (row.last - row.first).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
          {report.makes && (
            <p className="detail">
              Makes in the first half of your sessions: {pct(report.makes.early)}. Second half: {pct(report.makes.late)}.{" "}
              {report.makes.clear ? "That gap is bigger than luck alone would give." : "That gap could still be luck."}
            </p>
          )}
        </>
      )}
    </>
  );
}

const pct = (half: { makes: number; shots: number }) => `${Math.round((100 * half.makes) / half.shots)}%`;
