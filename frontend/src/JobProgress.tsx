import { useRef, type CSSProperties } from "react";
import { formatTime } from "./format";
import type { Progress } from "./types";

// The three things that happen to a clip, in order. Each has its own piece of the bar,
// and `share` is how wide that piece is (the slow steps get more room).
const STAGES = [
  { key: "upload", label: "Upload", share: 1 },
  { key: "detect", label: "Find shots", share: 3 },
  { key: "form", label: "Measure form", share: 1 },
] as const;

type Props = {
  filename: string;
  // Bytes sent so far, while the file is still going up. null once it has arrived.
  upload: { sent: number; total: number } | null;
  // What the server last said about the job. null before the detector has started.
  progress: Progress | null;
};

const megabytes = (bytes: number) => (bytes / 1_000_000).toFixed(1);

// A real progress bar: every piece fills from a count the browser or the server reported,
// never from a timer. Finished steps are full, the current one grows, later ones are empty.
export default function JobProgress({ filename, upload, progress }: Props) {
  const stage = upload ? "upload" : (progress?.stage ?? "detect");
  const current = STAGES.findIndex((s) => s.key === stage);
  const done = upload ? upload.sent : (progress?.done ?? 0);
  const total = upload ? upload.total : (progress?.total ?? 0);
  // Before the detector reports its first frame there is no count yet.
  const counted = total > 0;
  const fraction = counted ? Math.min(1, done / total) : 0;
  const percent = Math.floor(fraction * 100);

  // Time left in this step, from how fast the count has moved since the step began.
  const started = useRef({ stage, done, at: Date.now() });
  if (started.current.stage !== stage) started.current = { stage, done, at: Date.now() };
  const elapsed = (Date.now() - started.current.at) / 1000;
  const rate = (done - started.current.done) / elapsed;
  const secondsLeft = counted && elapsed > 3 && rate > 0 ? (total - done) / rate : null;

  let doing = "Getting the detector ready";
  if (upload) doing = `Uploading, ${megabytes(done)} of ${megabytes(total)} MB`;
  else if (counted && stage === "detect") doing = `Finding shots, frame ${done.toLocaleString()} of ${total.toLocaleString()}`;
  else if (counted) doing = `Measuring form, shot ${done} of ${total}`;

  return (
    <div className="job">
      <h2>{filename}</h2>
      {/* The big number is how far the current step is, so it is labelled with the step. */}
      <div className="job-now">
        {counted && <strong>{percent}%</strong>}
        <p>
          <span className="detail">{counted ? "of step" : "Step"} {current + 1} of {STAGES.length}</span>
          <span>{doing}</span>
        </p>
      </div>

      <ol
        className="job-bar"
        role="progressbar"
        aria-label={`Processing ${filename}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={counted ? percent : undefined}
        aria-valuetext={`Step ${current + 1} of ${STAGES.length}, ${STAGES[current].label}` + (counted ? `, ${percent}%` : "")}
      >
        {STAGES.map((s, index) => {
          const state = index < current ? "done" : index === current ? "active" : "waiting";
          const filled = index < current ? 1 : index === current ? fraction : 0;
          return (
            <li key={s.key} className={state} style={{ "--share": s.share } as CSSProperties}>
              <div className={state === "active" && !counted ? "track busy" : "track"}>
                <div className="fill" style={{ width: `${filled * 100}%` }} />
              </div>
              <span>{s.label}</span>
            </li>
          );
        })}
      </ol>

      <p className="detail">
        {secondsLeft !== null && `About ${formatTime(secondsLeft)} left in this step. `}
        {upload
          ? "Keep this page open until the upload finishes."
          : "The work happens on the server, so you can leave and come back."}
      </p>
    </div>
  );
}
