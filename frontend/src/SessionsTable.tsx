import { formatDate, formatPct } from "./format";
import type { SessionSummary } from "./types";

type Props = {
  sessions: SessionSummary[];
  selectedId: string | undefined;
  disabled: boolean;
  onSelect: (id: string) => void;
  onDelete: (row: SessionSummary) => void;
};

export default function SessionsTable({ sessions, selectedId, disabled, onSelect, onDelete }: Props) {
  return (
    <section>
      <h2>Sessions</h2>
      {sessions.length === 0 ? (
        <p className="detail">No sessions yet. Upload a clip to start.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Clip</th>
              <th className="wide-only">Date</th>
              <th className="num">Makes</th>
              <th className="num">Misses</th>
              <th className="num">FG%</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {sessions.map((row) => {
              // Only finished sessions have a video to open.
              const canOpen = row.status === "COMPLETED" && !disabled;
              const classes = [canOpen && "clickable", row.id === selectedId && "selected"];
              return (
                // Clicking anywhere on the row opens it. The button is there for the keyboard:
                // Tab focuses it, Enter clicks it, and that click bubbles up to the row.
                <tr
                  key={row.id}
                  className={classes.filter(Boolean).join(" ")}
                  onClick={canOpen ? () => onSelect(row.id) : undefined}
                >
                  <td className="clip">
                    {canOpen ? <button type="button">{row.original_filename}</button> : row.original_filename}
                  </td>
                  <td className="wide-only">{formatDate(row.created_at)}</td>
                  <td className="num">{row.makes}</td>
                  <td className="num">{row.misses}</td>
                  <td className="num">
                    {row.status === "COMPLETED" ? (
                      formatPct(row.shooting_pct)
                    ) : (
                      <span className="detail">{row.status.toLowerCase()}</span>
                    )}
                  </td>
                  <td className="num">
                    <button
                      type="button"
                      className="text-button"
                      aria-label={`Delete ${row.original_filename}`}
                      disabled={disabled}
                      onClick={(event) => {
                        event.stopPropagation(); // don't also open the row
                        onDelete(row);
                      }}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
