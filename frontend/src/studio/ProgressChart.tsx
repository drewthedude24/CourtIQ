import { useEffect, useRef, useState } from "react";
import { formatDate, formatPct } from "../format";
import type { SessionSummary } from "../types";

// Space around the plot, in pixels: room for the 0/50/100 labels, the % above each dot,
// and the session numbers underneath.
const LEFT = 40;
const RIGHT = 20;
const TOP = 28;
const BOTTOM = 28;
const HEIGHT = 220;
// With more sessions than this, only some dots get their % printed.
const MAX_LABELS = 12;

type Props = {
  // Every session, newest first, as GET /api/sessions sends them.
  sessions: SessionSummary[];
  openId: string | undefined;
  onOpen: (id: string) => void;
};

// Field goal % for each finished session, oldest on the left. Click a dot to open that session.
// Drawn in real pixels for the width it gets, so the text stays the same size on a phone.
export default function ProgressChart({ sessions, openId, onOpen }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(box.current!);
    return () => observer.disconnect();
  }, []);

  // Session numbers count every upload, oldest is 1, the same as the session picker.
  const points = sessions
    .map((row, index) => ({ row, number: sessions.length - index }))
    .filter(({ row }) => row.status === "COMPLETED" && row.shooting_pct !== null)
    .reverse();

  const plot = width - LEFT - RIGHT;
  const x = (i: number) => (points.length === 1 ? LEFT + plot / 2 : LEFT + (i * plot) / (points.length - 1));
  const y = (pct: number) => TOP + ((100 - pct) * (HEIGHT - TOP - BOTTOM)) / 100;
  const every = Math.ceil(points.length / MAX_LABELS);
  // Counted back from the newest, so the newest is always labelled.
  const labelled = (i: number) => (points.length - 1 - i) % every === 0;

  return (
    <div className="progress-chart" ref={box}>
      {width > 0 && points.length > 0 && (
        <svg width={width} height={HEIGHT} role="img" aria-label={`Field goal % by session. Newest: ${formatPct(points[points.length - 1].row.shooting_pct)}.`}>
          {[0, 50, 100].map((tick) => (
            <g key={tick}>
              <line className="grid" x1={LEFT} x2={width - RIGHT} y1={y(tick)} y2={y(tick)} />
              <text className="axis" x={LEFT - 8} y={y(tick) + 4} textAnchor="end">{tick}%</text>
            </g>
          ))}
          <polyline className="line" points={points.map((p, i) => `${x(i)},${y(p.row.shooting_pct!)}`).join(" ")} />
          {points.map((p, i) => {
            const open = p.row.id === openId;
            const label = `Session ${p.number}, ${p.row.original_filename}, ${formatDate(p.row.created_at)}: ${formatPct(p.row.shooting_pct)}`;
            return (
              <g
                key={p.row.id}
                className={open ? "point open" : "point"}
                role="button"
                tabIndex={0}
                aria-label={`Open ${label}`}
                onClick={() => onOpen(p.row.id)}
                onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && onOpen(p.row.id)}
              >
                <title>{label}</title>
                {/* A bigger invisible circle, so the dot is easy to hit with a finger. */}
                <circle className="hit" cx={x(i)} cy={y(p.row.shooting_pct!)} r={16} />
                <circle className="dot" cx={x(i)} cy={y(p.row.shooting_pct!)} r={open ? 6 : 4.5} />
                {(labelled(i) || open) && (
                  <text className="value" x={x(i)} y={y(p.row.shooting_pct!) - 12} textAnchor="middle">
                    {Math.round(p.row.shooting_pct!)}%
                  </text>
                )}
                {(labelled(i) || open) && (
                  <text className="axis" x={x(i)} y={HEIGHT - 8} textAnchor="middle">{p.number}</text>
                )}
              </g>
            );
          })}
        </svg>
      )}
      <p className="detail caption">Session number underneath. Click a dot to open that session.</p>
    </div>
  );
}
