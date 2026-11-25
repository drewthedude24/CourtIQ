import { FORM_COLUMNS, formatDate, formatNumber, formatPct } from "./format";
import type { FormTrendRow } from "./types";

type ChartProps = {
  rows: FormTrendRow[];
  label: string;
  value: (row: FormTrendRow) => number | null;
  // How much the number changed from shot to shot in that session. 0 draws no bar.
  spread: (row: FormTrendRow) => number;
  print: (value: number) => string;
  // Extra words for the hover text, such as how many shots the average is based on.
  detail: (row: FormTrendRow) => string;
};

// The drawing area of one chart, in SVG units. The plot sits inside the margins.
const WIDTH = 220;
const HEIGHT = 150;
const LEFT = 12;
const RIGHT = 12;
const TOP = 26;
const BOTTOM = 24;
// With more sessions than this the names under the dots would overlap.
const MAX_NAMES = 6;

// One number across the sessions, oldest on the left. Each dot is a session's average.
// The thin bar through it reaches one spread up and one down: how much that number changed
// from shot to shot inside the session.
function TrendChart({ rows, label, value, spread, print, detail }: ChartProps) {
  const points = rows.flatMap((row, index) => {
    const average = value(row);
    return average === null ? [] : [{ row, index, value: average, spread: spread(row) }];
  });
  if (points.length === 0) return null;

  // The up-and-down scale runs from the lowest bar end to the highest.
  const low = Math.min(...points.map((point) => point.value - point.spread));
  const high = Math.max(...points.map((point) => point.value + point.spread));
  const x = (index: number) =>
    rows.length === 1 ? WIDTH / 2 : LEFT + (index * (WIDTH - LEFT - RIGHT)) / (rows.length - 1);
  const y = (value: number) =>
    high === low ? HEIGHT / 2 : TOP + ((high - value) * (HEIGHT - TOP - BOTTOM)) / (high - low);
  const last = points.length - 1;

  return (
    <figure>
      <figcaption>{label}</figcaption>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={`${label} by session`}>
        <polyline className="trend-line" points={points.map((p) => `${x(p.index)},${y(p.value)}`).join(" ")} />
        {points.map((point, i) => (
          <g key={point.row.id}>
            {point.spread > 0 && (
              <line
                className="trend-spread"
                x1={x(point.index)} x2={x(point.index)}
                y1={y(point.value - point.spread)} y2={y(point.value + point.spread)}
              />
            )}
            <circle className="trend-dot" cx={x(point.index)} cy={y(point.value)} r={4} />
            {/* Only the first and last values are printed. The rest show on hover and in the table. */}
            {(i === 0 || i === last) && (
              <text
                className="trend-value"
                x={x(point.index)}
                y={y(point.value + point.spread) - 6}
                textAnchor={last === 0 ? "middle" : i === 0 ? "start" : "end"}
              >
                {print(point.value)}
              </text>
            )}
            {(rows.length <= MAX_NAMES || i === 0 || i === last) && (
              <text className="trend-name" x={x(point.index)} y={HEIGHT - 6} textAnchor="middle">
                {point.row.original_filename.replace(/\.\w+$/, "")}
              </text>
            )}
            {/* A bigger invisible circle, so the dot is easy to hover. */}
            <circle cx={x(point.index)} cy={y(point.value)} r={12} fill="transparent">
              <title>
                {`${point.row.original_filename}: ${print(point.value)}, ${detail(point.row)}`}
              </title>
            </circle>
          </g>
        ))}
      </svg>
    </figure>
  );
}

// Each session's average form numbers, oldest first, to see them change over time.
export default function FormTrend({ rows }: { rows: FormTrendRow[] }) {
  if (rows.length === 0) return null;

  return (
    <section className="form-trend">
      <h2>Form over time</h2>
      <p className="detail caption">
        Oldest session on the left. Each dot is a session's average. The thin bar is how much the
        number changed from shot to shot in that session, so a gap smaller than the bars is noise.
        Hover a dot to see how many shots it is based on.
      </p>
      <div className="charts">
        <TrendChart
          rows={rows}
          label="Shots made"
          value={(row) => row.shooting_pct}
          spread={() => 0}
          print={formatPct}
          detail={(row) => `${row.shots} shots`}
        />
        {FORM_COLUMNS.map((column) => {
          const print = (value: number) => formatNumber(value, column.digits, column.unit);
          return (
            <TrendChart
              key={column.key}
              rows={rows}
              label={column.label}
              value={(row) => row[column.key]}
              spread={(row) => row[`${column.key}_spread`] ?? 0}
              print={print}
              detail={(row) =>
                `spread ${print(row[`${column.key}_spread`] ?? 0)}, ` +
                `measured on ${row[`${column.key}_shots`]} of ${row.shots} shots`
              }
            />
          );
        })}
      </div>
      <table>
        <thead>
          <tr>
            <th>Clip</th>
            <th className="wide-only">Date</th>
            {FORM_COLUMNS.map((column) => (
              <th key={column.key} className="num">{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td className="clip">{row.original_filename}</td>
              <td className="wide-only">{formatDate(row.created_at)}</td>
              {FORM_COLUMNS.map((column) => (
                <td key={column.key} className="num">
                  {formatNumber(row[column.key], column.digits, column.unit)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
