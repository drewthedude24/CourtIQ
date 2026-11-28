import { useEffect, useRef, useState } from "react";
import ShotTape from "../ShotTape";
import { FORM_COLUMNS, formatNumber, formatTime } from "../format";
import type { Session, Shot } from "../types";

// A shot is played from a little before the detected moment, so you see it go up,
// until a little after, so you see it land.
const LEAD_IN_S = 2;
const AFTER_S = 1.5;

type Props = {
  session: Session;
  request: { sessionId: string; shot: Shot; at: number } | null;
};

// The video with a shot review panel beside it. The panel follows the video: whatever shot
// is playing is the current shot, so stepping, the timeline and the key points always agree.
export default function Replay({ session, request }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [slow, setSlow] = useState(false);
  const shots = session.shots;

  // The current shot is the last one whose window has started. -1 before the first shot.
  let current = -1;
  shots.forEach((item, index) => {
    if (item.timestamp_s - LEAD_IN_S <= time) current = index;
  });
  const shot = current >= 0 ? shots[current] : null;

  function play(target: Shot) {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = Math.max(0, target.timestamp_s - LEAD_IN_S);
    setTime(video.currentTime); // Move the panel now, not on the next timeupdate.
    video.play();
  }

  // A shot picked on the Shot review tab. The video may still be loading, so wait for it.
  useEffect(() => {
    if (!request || request.sessionId !== session.id) return;
    const video = videoRef.current;
    if (!video) return;
    if (video.readyState >= 1) play(request.shot);
    else video.addEventListener("loadedmetadata", () => play(request.shot), { once: true });
  }, [request?.at]);

  useEffect(() => {
    if (videoRef.current) videoRef.current.playbackRate = slow ? 0.5 : 1;
  }, [slow]);

  // How far the video is through the current shot's window, for the small timeline.
  const start = shot ? Math.max(0, shot.timestamp_s - LEAD_IN_S) : 0;
  const end = shot ? Math.min(duration || Infinity, shot.timestamp_s + AFTER_S) : 0;
  const through = shot ? Math.min(1, Math.max(0, (time - start) / (end - start))) : 0;
  const pictures = shot ? FORM_COLUMNS.filter((column) => shot.pictures[column.key]) : [];

  return (
    <section className="replay">
      <div className="stage">
        <div className="frame">
          <video
            ref={videoRef}
            src={session.video_url ?? undefined}
            controls
            autoPlay
            muted
            playsInline
            onLoadedMetadata={(event) => setDuration(event.currentTarget.duration)}
            onTimeUpdate={(event) => setTime(event.currentTarget.currentTime)}
          />
        </div>
        <ShotTape shots={shots} duration={duration} time={time} picked={shot?.shot_number ?? null} onJump={play} />
      </div>

      <div className="side">
        <aside className="review" aria-label="Replay">
          <h2>Replay</h2>
          {shots.length === 0 ? (
            <p className="detail">No shots found in this clip. CourtIQ needs to see both the ball and the hoop.</p>
          ) : (
            <>
              <div className="review-now" aria-live="polite">
                <span className="review-number">
                  {shot ? `Shot ${shot.shot_number}` : "Up next: shot 1"}
                  <span className="detail"> of {shots.length}</span>
                </span>
                {shot && (
                  // Keyed by shot, so a new verdict pops in when the shot changes.
                  <strong key={shot.shot_number} className={shot.result === "MAKE" ? "make" : "miss"}>
                    {shot.result === "MAKE" ? "Make" : "Miss"}
                  </strong>
                )}
              </div>

              <div className="window" aria-hidden={!shot}>
                <div className="window-line">
                  <div className="window-fill" style={{ width: `${through * 100}%` }} />
                </div>
                <div className="window-ends detail">
                  <span>{shot ? formatTime(start) : "-"}</span>
                  <span>{shot ? formatTime(end) : "-"}</span>
                </div>
              </div>

              <div className="review-controls">
                <button type="button" disabled={current <= 0} onClick={() => play(shots[current - 1])}>
                  <Chevron flip /> Previous
                </button>
                <button type="button" onClick={() => play(shot ?? shots[0])}>
                  {shot ? "Replay" : "Play"}
                </button>
                <button type="button" disabled={current >= shots.length - 1} onClick={() => play(shots[current + 1])}>
                  Next <Chevron />
                </button>
              </div>
              <label className="slow">
                <input type="checkbox" checked={slow} onChange={(event) => setSlow(event.target.checked)} />
                Half speed
              </label>

              <ol className="chips" aria-label="Every shot">
                {shots.map((item, index) => (
                  <li key={item.shot_number}>
                    <button
                      type="button"
                      className={item.result === "MAKE" ? "make" : "miss"}
                      aria-current={index === current ? "true" : undefined}
                      aria-label={`Shot ${item.shot_number}, ${item.result === "MAKE" ? "make" : "miss"}, at ${formatTime(item.timestamp_s)}`}
                      onClick={() => play(item)}
                    >
                      {item.shot_number}
                    </button>
                  </li>
                ))}
              </ol>
            </>
          )}
        </aside>

        {shot && (
          <section className="keypoints" aria-label={`Form on shot ${shot.shot_number}`}>
            <h2>Key points, shot {shot.shot_number}</h2>
            {pictures.length > 0 ? (
              <div className="keypoint-row">
                {pictures.map((column) => (
                  <figure key={column.key}>
                    <img src={shot.pictures[column.key]} alt={`Shot ${shot.shot_number}, where ${column.label.toLowerCase()} was read`} />
                    <figcaption>
                      <span>{column.label}</span>
                      <b>{formatNumber(shot[column.key], column.digits, column.unit)}</b>
                    </figcaption>
                  </figure>
                ))}
              </div>
            ) : (
              <p className="detail">Form wasn't measured on this shot.</p>
            )}
            {pictures.length > 0 && (
              <p className="detail caption">
                The frame each number was read on, with the joints it uses drawn in green. Knee and arm
                come from heights, so from behind the drawn lines can look straighter than the number.
              </p>
            )}
          </section>
        )}
      </div>
    </section>
  );
}

function Chevron({ flip }: { flip?: boolean }) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" style={flip ? { transform: "scaleX(-1)" } : undefined}>
      <path d="M6 3.5 10.5 8 6 12.5" />
    </svg>
  );
}
