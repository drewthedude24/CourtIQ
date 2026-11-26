import { formatMonth, formatPct } from "./format";
import type { Stats } from "./types";

export default function StatsPanel({ stats }: { stats: Stats | null }) {
  if (!stats) return null;

  return (
    <section id="months">
      <h2>Shooting by month</h2>
      <p className="detail caption">Makes and misses across all sessions.</p>
      {stats.months.length === 0 ? (
        <p className="detail">No shots yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Month</th>
              <th className="num">Makes</th>
              <th className="num">Misses</th>
              <th className="num">Shooting %</th>
            </tr>
          </thead>
          <tbody>
            {stats.months.map((row) => (
              <tr key={row.month}>
                <td>{formatMonth(row.month)}</td>
                <td className="num">{row.makes}</td>
                <td className="num">{row.misses}</td>
                <td className="num">{formatPct(row.shooting_pct)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">All time</th>
              <td className="num">{stats.overall.makes}</td>
              <td className="num">{stats.overall.misses}</td>
              <td className="num">{formatPct(stats.overall.shooting_pct)}</td>
            </tr>
          </tfoot>
        </table>
      )}
    </section>
  );
}
