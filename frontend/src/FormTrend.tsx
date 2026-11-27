import { useState } from "react";
import { FORM_COLUMNS, formatDate, formatNumber, formatPct } from "./format";
import type { FormTrendRow } from "./types";

type Accessor = (row: FormTrendRow) => number | null;

type ChartProps = {
  rows: FormTrendRow[];
  label: string;
  value: Accessor;
  // How many shots each session's average rests on, to weight the all-time average.
  shots: (row: FormTrendRow) => number;
  // How much the number changes from shot to shot inside a session. null for shooting %.
  spread: Accessor;
  print: (value: number) => string;
  // Shooting % runs on a fixed 0 to 100 scale, and its lines are green going up, red going down.
  shooting?: boolean;
  // The session under the pointer (its index in rows), shared by every chart and the table.
  hovered: number | null;
  onHover: (index: number | null) => void;
};

// The drawing area of one chart, in SVG units. The plot sits inside the margins.
const WIDTH = 300;
const HEIGHT = 130;
const LEFT = 34;
const RIGHT = 10;
const TOP = 8;
const BOTTOM = 22;
// With more sessions than this, only some session numbers are printed under the chart.
const MAX_NUMBERS = 12;

// Your usual range for one number: the all-time average (each session weighted by its
// shots), plus or minus the usual shot-to-shot spread (the sessions' spreads, averaged the
// same way). A session average outside it moved more than the number normally wobbles.
function usualRange(rows: FormTrendRow[], value: Accessor, spread: Accessor, shots: ChartProps["shots"]) {
  let total = 0, sum = 0, spreadTotal = 0, spreadSum = 0;
  for (const row of rows) {
    const average = value(row);
    if (average === null) continue;
    total += shots(row);
    sum += average * shots(row);
    const wobble = spread(row);
    if (wobble !== null) {
      spreadTotal += shots(row);
      spreadSum += wobble * shots(row);
    }
  }
  return { average: sum / total, spread: spreadTotal ? spreadSum / spreadTotal : 0 };
}

function isOdd(value: number, range: { average: number; spread: number }) {
  return range.spread > 0 && Math.abs(value - range.average) > range.spread;
}

// Two to four round numbers for the side of the chart that cover low to high, like 90, 95, 100.
function roundTicks(low: number, high: number) {
  const rough = (high - low || Math.abs(high) || 1) / 2;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 5, 10].map((m) => m * power).find((s) => s >= rough)!;
  const first = Math.floor(low / step);
  const last = Math.max(Math.ceil(high / step), first + 1);
  const digits = Math.max(0, -Math.floor(Math.log10(step)));
  const ticks = [];
  for (let i = first; i <= last; i++) ticks.push({ value: i * step, text: (i * step).toFixed(digits) });
  return ticks;
}

// A small arrow like the ones painted on a road: up, down, or a flat bar when nothing changed.
function Arrow({ direction }: { direction: "up" | "down" | "same" }) {
  return (
    <svg className="trend-arrow" viewBox="0 0 12 12" aria-hidden="true">
      {direction === "same" ? (
        <rect x="1" y="4.5" width="10" height="3" />
      ) : (
        <path d="M6 0.5 L11.5 6.5 H8 V11.5 H4 V6.5 H0.5 Z"
          transform={direction === "down" ? "rotate(180 6 6)" : undefined} />
      )}
    </svg>
  );
}

// One number across the sessions, oldest on the left. Each dot is a session's average.
function TrendChart({ rows, label, value, shots, spread, print, shooting, hovered, onHover }: ChartProps) {
  const points = rows.flatMap((row, index) => {
    const average = value(row);
    return average === null ? [] : [{ row, index, value: average }];
  });
  if (points.length === 0) {
    return (
      <figure className="trend">
        <figcaption><span className="trend-label">{label}</span></figcaption>
        <p className="detail">Not measured yet.</p>
      </figure>
    );
  }

  const range = usualRange(rows, value, spread, shots);
  const values = points.map((point) => point.value);
  const ticks = shooting
    ? roundTicks(0, 100)
    : roundTicks(Math.min(...values, range.average - range.spread), Math.max(...values, range.average + range.spread));
  const bottom = ticks[0].value;
  const top = ticks[ticks.length - 1].value;
  const x = (index: number) =>
    rows.length === 1 ? (LEFT + WIDTH - RIGHT) / 2 : LEFT + (index * (WIDTH - LEFT - RIGHT)) / (rows.length - 1);
  const y = (v: number) => TOP + ((top - v) * (HEIGHT - TOP - BOTTOM)) / (top - bottom);
  // Half the gap between two sessions: each session owns the strip of chart around its dot.
  const half = rows.length === 1 ? WIDTH / 2 : (WIDTH - LEFT - RIGHT) / (rows.length - 1) / 2;
  const every = Math.ceil(rows.length / MAX_NUMBERS);
  // Smaller dots when there are many sessions, so they don't run into each other.
  const dot = rows.length > 15 ? 3 : 4;

  // The header shows the session under the pointer, or the newest one, and the change from
  // the last session before it where this number was measured.
  const target = hovered ?? rows.length - 1;
  const shown = points.find((point) => point.index === target);
  const before = points.filter((point) => point.index < target).pop();
  const direction = !shown || !before || print(shown.value) === print(before.value)
    ? "same" : shown.value > before.value ? "up" : "down";

  return (
    <figure className="trend">
      <figcaption>
        <span className="trend-label">{label}</span>
        {shown ? (
          <span className="trend-now">
            <b className={!shooting && isOdd(shown.value, range) ? "odd" : undefined}>{print(shown.value)}</b>
            {before ? (
              <span className={`trend-change${shooting ? ` ${direction}` : ""}`}>
                <Arrow direction={direction} />
                {direction === "same" ? "same as" : "from"} {print(before.value)}
              </span>
            ) : (
              <span className="trend-change">first session</span>
            )}
          </span>
        ) : (
          <span className="trend-now"><b>-</b><span className="trend-change">not measured this session</span></span>
        )}
      </figcaption>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`${label} by session. Newest: ${print(points[points.length - 1].value)}. Every value is in the table below.`}
        onPointerLeave={(event) => event.pointerType === "mouse" && onHover(null)}
      >
        {ticks.map((tick) => (
          <g key={tick.text}>
            <line className="trend-grid" x1={LEFT} x2={WIDTH} y1={y(tick.value)} y2={y(tick.value)} />
            <text className="trend-axis" x={LEFT - 6} y={y(tick.value) + 4} textAnchor="end">{tick.text}</text>
          </g>
        ))}
        {range.spread > 0 && (
          <rect className="trend-band" x={LEFT} width={WIDTH - LEFT}
            y={y(range.average + range.spread)} height={y(range.average - range.spread) - y(range.average + range.spread)} />
        )}
        <line className="trend-average" x1={LEFT} x2={WIDTH} y1={y(range.average)} y2={y(range.average)} />
        {hovered !== null && <line className="trend-cursor" x1={x(hovered)} x2={x(hovered)} y1={TOP} y2={HEIGHT - BOTTOM} />}
        {points.slice(1).map((point, i) => {
          const from = points[i];
          const change = shooting && point.value !== from.value ? (point.value > from.value ? " up" : " down") : "";
          return (
            <line key={point.row.id} className={`trend-line${change}`}
              x1={x(from.index)} y1={y(from.value)} x2={x(point.index)} y2={y(point.value)} />
          );
        })}
        {points.map((point) => (
          <g key={point.row.id}>
            {!shooting && isOdd(point.value, range) && (
              <circle className="trend-odd" cx={x(point.index)} cy={y(point.value)} r={dot + 3.5} />
            )}
            <circle className="trend-dot" cx={x(point.index)} cy={y(point.value)} r={(point.index === hovered ? 1.5 : 0) + dot} />
          </g>
        ))}
        {rows.map((row, index) =>
          // Counted back from the newest, so the newest number is always printed.
          (rows.length - 1 - index) % every === 0 && (
            <text key={row.id} className="trend-axis" x={x(index)} y={HEIGHT - 4} textAnchor="middle">{index + 1}</text>
          ),
        )}
        {/* An invisible strip per session, so pointing anywhere above a session picks it. */}
        {rows.map((row, index) => (
          <rect key={row.id} x={x(index) - half} width={2 * half} y={0} height={HEIGHT}
            fill="transparent" onPointerEnter={() => onHover(index)} />
        ))}
      </svg>
    </figure>
  );
}

// Each session's average form numbers, oldest first, to see them change over time.
export default function FormTrend({ rows }: { rows: FormTrendRow[] }) {
  const [hovered, setHovered] = useState<number | null>(null);
  if (rows.length === 0) return null;

  return (
    <section id="trend" className="form-trend">
      <h2>Form over time</h2>
      <p className="detail caption">
        Each dot is one session's average, oldest on the left. The shaded band is your usual
        range: your all-time average, plus or minus how much the number usually changes from
        shot to shot. A yellow ring means a session moved more than that.
        {rows.length === 1 ? " Upload another session to see a trend." : " Point at a session to see its numbers."}
      </p>
      <p className="trend-showing">
        Showing session {(hovered ?? rows.length - 1) + 1}
        {hovered === null && rows.length > 1 ? " (newest)" : ""}: {rows[hovered ?? rows.length - 1].original_filename},{" "}
        {formatDate(rows[hovered ?? rows.length - 1].created_at)}
      </p>
      <div className="charts">
        <TrendChart
          rows={rows}
          label="Shooting %"
          value={(row) => row.shooting_pct}
          shots={(row) => row.shots}
          spread={() => null}
          print={formatPct}
          shooting
          hovered={hovered}
          onHover={setHovered}
        />
        {FORM_COLUMNS.map((column) => (
          <TrendChart
            key={column.key}
            rows={rows}
            label={column.label}
            value={(row) => row[column.key]}
            shots={(row) => row[`${column.key}_shots`]}
            spread={(row) => row[`${column.key}_spread`]}
            print={(value) => formatNumber(value, column.digits, column.unit)}
            hovered={hovered}
            onHover={setHovered}
          />
        ))}
      </div>
      <table>
        <thead>
          <tr>
            <th className="num">#</th>
            <th>Clip</th>
            <th className="wide-only">Date</th>
            <th className="num wide-only">Shooting %</th>
            {FORM_COLUMNS.map((column) => (
              <th key={column.key} className="num">{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={row.id}
              className={index === hovered ? "hovered" : undefined}
              onMouseEnter={() => setHovered(index)}
              onMouseLeave={() => setHovered(null)}
            >
              <td className="num">{index + 1}</td>
              <td className="clip">{row.original_filename}</td>
              <td className="wide-only">{formatDate(row.created_at)}</td>
              <td className="num wide-only">{formatPct(row.shooting_pct)}</td>
              {FORM_COLUMNS.map((column) => {
                const average = row[column.key];
                const range = usualRange(rows, (r) => r[column.key], (r) => r[`${column.key}_spread`], (r) => r[`${column.key}_shots`]);
                return (
                  <td key={column.key} className={average !== null && isOdd(average, range) ? "num odd" : "num"}>
                    {formatNumber(average, column.digits, column.unit)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
