import { useState } from "react";
import { roundTicks } from "./FormTrend";
import { formatDate } from "./format";
import type { FatigueReport } from "./types";

// The drawing area of the chart, in SVG units. The plot sits inside the margins.
const WIDTH = 640;
const HEIGHT = 260;
// Wide enough on the left and bottom for the bigger axis text a phone gets (App.css).
const LEFT = 52;
const RIGHT = 12;
const TOP = 10;
const BOTTOM = 26;

// -12.4 -> "−12%", 3.2 -> "+3%". A real minus sign, so it lines up with the plus.
function signedPct(value: number) {
  const rounded = Math.round(value);
  return `${rounded > 0 ? "+" : rounded < 0 ? "−" : ""}${Math.abs(rounded)}%`;
}

const pct = (makes: number, shots: number) => `${Math.round((100 * makes) / shots)}%`;

// How a shooter's jump changes through a session (backend/fatigue.py). Each dot is one shot.
export default function Fatigue({ report }: { report: FatigueReport | null }) {
  // The session picked in the table (its index), drawn on top of the others in the chart.
  const [picked, setPicked] = useState<number | null>(null);
  if (!report || report.sessions.length === 0) return null;
  const { model, sessions, makes } = report;

  const jumps = sessions.flatMap((session) => session.shots.map((shot) => shot.jump));
  const lastShot = Math.max(...sessions.flatMap((session) => session.shots.map((shot) => shot.shot_number)));
  const ticks = roundTicks(Math.min(...jumps), Math.max(...jumps), 4);
  const bottom = ticks[0].value;
  const top = ticks[ticks.length - 1].value;
  const x = (shotNumber: number) => LEFT + ((shotNumber - 1) * (WIDTH - LEFT - RIGHT)) / Math.max(lastShot - 1, 1);
  const y = (jump: number) => TOP + ((top - jump) * (HEIGHT - TOP - BOTTOM)) / (top - bottom);
  const every = Math.ceil(lastShot / 12);

  // The line drawn in bold: the picked session's own, or the trend from the average start.
  const shown = picked === null ? null : sessions[picked];
  const line = model && (shown
    ? { start: shown.start!, end: shown.end!, shots: Math.max(...shown.shots.map((shot) => shot.shot_number)) }
    : { start: model.start, end: model.start + model.per_shot * (lastShot - 1), shots: lastShot });
  const missing = model ? 0 : 3 - sessions.length;

  return (
    <section id="fatigue" className="fatigue">
      <h2>Fatigue</h2>
      <p className="detail caption">
        When legs tire, the jump is the first thing to go, so that is what this tracks. Each mark
        is one shot: how high you jumped, in the order you shot. Jump is measured in
        shoulder-heights (0.25 means your feet rose a quarter of your standing shoulder height).
      </p>

      {model ? (
        <p className="totals fatigue-totals">
          <span><b>{signedPct(model.drop_pct)}</b> jump from first shot to last, over {model.typical_shots} shots</span>
          <span><b>{model.dropped} of {model.sessions}</b> sessions ended lower than they started</span>
        </p>
      ) : (
        <p className="trend-showing">
          Upload {missing} more {missing === 1 ? "session" : "sessions"} with at least 5 shots to fit a trend.
        </p>
      )}

      <div className="fatigue-body">
        <figure className="fatigue-chart">
          <svg
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            role="img"
            aria-label={
              model
                ? `Jump by shot number. The trend goes from ${model.start.toFixed(2)} on the first shot to ${(model.start + model.per_shot * (model.typical_shots - 1)).toFixed(2)} on shot ${model.typical_shots}. Each session is in the table below.`
                : "Jump by shot number. Each session is in the table below."
            }
          >
            {ticks.map((tick) => (
              <g key={tick.text}>
                <line className="trend-grid" x1={LEFT} x2={WIDTH - RIGHT} y1={y(tick.value)} y2={y(tick.value)} />
                <text className="trend-axis" x={LEFT - 8} y={y(tick.value) + 4} textAnchor="end">{tick.text}</text>
              </g>
            ))}
            {sessions.map((session, index) => (
              <g key={session.id} className={picked === null ? "fatigue-session" : index === picked ? "fatigue-session picked" : "fatigue-session faded"}>
                <polyline className="fatigue-path" points={session.shots.map((shot) => `${x(shot.shot_number)},${y(shot.jump)}`).join(" ")} />
                {session.shots.map((shot) => (
                  <circle key={shot.shot_number} className={shot.result === "MAKE" ? "fatigue-make" : "fatigue-miss"}
                    cx={x(shot.shot_number)} cy={y(shot.jump)} r={shot.result === "MAKE" ? 4 : 3.25} />
                ))}
              </g>
            ))}
            {line && <line className="fatigue-trend" x1={x(1)} y1={y(line.start)} x2={x(line.shots)} y2={y(line.end)} />}
            {Array.from({ length: lastShot }, (_, index) => index + 1).map((shotNumber) =>
              (shotNumber - 1) % every === 0 && (
                <text key={shotNumber} className="trend-axis" x={x(shotNumber)} y={HEIGHT - 6} textAnchor="middle">{shotNumber}</text>
              ),
            )}
          </svg>
          <p className="detail fatigue-axis">Shot number in the session</p>
          <figcaption className="fatigue-key detail">
            <span className="make">Make</span>
            <span className="miss">Miss</span>
            {model && <span className="fatigue-key-trend">{shown ? `Trend for ${shown.original_filename}` : "Trend across all sessions"}</span>}
          </figcaption>
        </figure>

        <dl className="fatigue-facts">
          {model && (
            <div>
              <dt>Does the trend hold up?</dt>
              <dd>
                {model.check.with_trend < model.check.without
                  ? `Yes, a little. Guessing the jumps of a session it never saw, the trend was off by ${model.check.with_trend.toFixed(3)}. Guessing with no trend was off by ${model.check.without.toFixed(3)}.`
                  : `Not yet. Guessing the jumps of a session it never saw, the trend was off by ${model.check.with_trend.toFixed(3)}, no better than ${model.check.without.toFixed(3)} with no trend. Treat it as noise for now.`}
              </dd>
              <dd className="detail">
                Checked by leaving each session out in turn, fitting the trend on the others,
                and testing it on the one left out.
              </dd>
            </div>
          )}
          {makes && (
            <div>
              <dt>Do you miss more late in a session?</dt>
              <dd>
                First half: <b>{pct(makes.early.makes, makes.early.shots)}</b> ({makes.early.makes} of {makes.early.shots}).
                Second half: <b>{pct(makes.late.makes, makes.late.shots)}</b> ({makes.late.makes} of {makes.late.shots}).
              </dd>
              <dd className="detail">
                {makes.clear
                  ? "That gap is bigger than luck usually makes with this many shots."
                  : "With this few shots, a gap this size can be luck. More sessions will tell."}
              </dd>
            </div>
          )}
        </dl>
      </div>

      <table>
        <thead>
          <tr>
            <th className="num">#</th>
            <th>Clip</th>
            <th className="wide-only">Date</th>
            <th className="num">Shots</th>
            <th className="num">First 3 jumps</th>
            <th className="num">Last 3 jumps</th>
            <th className="num">Change</th>
          </tr>
        </thead>
        <tbody>
          {sessions.map((session, index) => (
            <tr
              key={session.id}
              className={index === picked ? "hovered" : undefined}
              onMouseEnter={() => setPicked(index)}
              onMouseLeave={() => setPicked(null)}
              onClick={() => setPicked(index)}
            >
              <td className="num">{index + 1}</td>
              <td className="clip">{session.original_filename}</td>
              <td className="wide-only">{formatDate(session.created_at)}</td>
              <td className="num">{session.shots.length}</td>
              <td className="num">{session.first.toFixed(2)}</td>
              <td className="num">{session.last.toFixed(2)}</td>
              <td className="num">{signedPct((100 * (session.last - session.first)) / session.first)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
