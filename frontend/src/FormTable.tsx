import { FORM_COLUMNS, formatNumber } from "./format";
import type { FormSummary, Session } from "./types";

// A number this many spreads away from the session's average is marked as unusual.
const ODD_SPREADS = 2;

type Props = {
  session: Session;
  // Called with a shot's time when its row is clicked, to play the video from there.
  onJump: (seconds: number) => void;
};

// The shooter's form on every shot of the open session, then the averages for makes,
// misses and all shots, and how much each number changes from shot to shot.
export default function FormTable({ session, onJump }: Props) {
  if (session.shots.length === 0) return null;

  const { makes, misses, all } = session.form;
  // Every measured shot has a flight time, so no flight time means no shot was measured.
  if (all.flight_time_s === null) {
    return (
      <section>
        <h2>Shot form</h2>
        <p className="detail">Form wasn't measured on this clip. Upload it again to measure it.</p>
      </section>
    );
  }

  // True when this shot's number is far from the session's average for that number.
  function isOdd(value: number | null, key: (typeof FORM_COLUMNS)[number]["key"]) {
    const average = all[key];
    const spread = all[`${key}_spread`];
    if (value === null || average === null || spread === null) return false;
    return Math.abs(value - average) > ODD_SPREADS * spread;
  }

  function averages(label: string, summary: FormSummary | null) {
    return (
      <tr>
        <th scope="row" colSpan={2}>{label}</th>
        {FORM_COLUMNS.map((column) => (
          <td key={column.key} className="num">
            {formatNumber(summary ? summary[column.key] : null, column.digits, column.unit)}
          </td>
        ))}
      </tr>
    );
  }

  return (
    <section>
      <h2>Shot form</h2>
      <p className="detail caption">
        Knee and elbow: the deepest bend before the release (180° is straight). Arm: how steeply it
        points up at the release. Jump: in shoulder-heights. Flight: from the hand to the rim.
        Click a shot to watch it. A number far from this session's average is{" "}
        <span className="odd">marked</span>.
      </p>
      <table>
        <thead>
          <tr>
            <th>Shot</th>
            <th>Result</th>
            {FORM_COLUMNS.map((column) => (
              <th key={column.key} className="num">{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {session.shots.map((shot) => (
            // Clicking anywhere on the row plays that shot. The button is there for the keyboard.
            <tr key={shot.shot_number} className="clickable" onClick={() => onJump(shot.timestamp_s)}>
              <td className="clip">
                <button type="button" aria-label={`Play shot ${shot.shot_number}`}>{shot.shot_number}</button>
              </td>
              <td className={shot.result === "MAKE" ? "make" : "miss"}>{shot.result}</td>
              {FORM_COLUMNS.map((column) => (
                <td key={column.key} className={isOdd(shot[column.key], column.key) ? "num odd" : "num"}>
                  {formatNumber(shot[column.key], column.digits, column.unit)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        <tfoot>
          {averages("Makes, average", makes)}
          {averages("Misses, average", misses)}
          {averages("All shots, average", all)}
          <tr>
            <th scope="row" colSpan={2}>Spread, all shots</th>
            {FORM_COLUMNS.map((column) => (
              <td key={column.key} className="num">
                {formatNumber(all[`${column.key}_spread`], column.digits, column.unit)}
              </td>
            ))}
          </tr>
          <tr>
            <th scope="row" colSpan={2}>Shots measured</th>
            {FORM_COLUMNS.map((column) => (
              <td key={column.key} className="num">
                {all[`${column.key}_shots`]}/{all.shots}
              </td>
            ))}
          </tr>
        </tfoot>
      </table>
    </section>
  );
}
