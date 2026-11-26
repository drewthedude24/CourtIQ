import { useRef, useState, type ReactNode } from "react";
import CourtScene from "./CourtScene";
import curryShooting from "./curry-shooting.jpg";
import FormPictures from "./FormPictures";
import FormTable from "./FormTable";
import JobProgress from "./JobProgress";
import ShotTape from "./ShotTape";
import { formatDate, formatTime } from "./format";
import type { Session, Shot } from "./types";

// Start playback a little before the detected moment, so you see the shot go up.
const LEAD_IN_S = 2;

type Props = {
  session: Session | null;
  // The file being uploaded and how much of it has been sent, or null.
  upload: { name: string; sent: number; total: number } | null;
  failed: boolean;
  // True when there are past sessions to pick from.
  hasHistory: boolean;
  uploadButton: ReactNode;
};

export default function Viewer({ session, upload, failed, hasHistory, uploadButton }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  // The clicked shot, whose form pictures show under the video. Kept with its session's id,
  // so opening another session doesn't show a shot from the last one.
  const [picked, setPicked] = useState<{ sessionId: string; shotNumber: number } | null>(null);
  // The video's length and where it is playing, for the shot tape.
  const [duration, setDuration] = useState(0);
  const [time, setTime] = useState(0);

  function jumpTo(shot: Shot) {
    if (session) setPicked({ sessionId: session.id, shotNumber: shot.shot_number });
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = Math.max(0, shot.timestamp_s - LEAD_IN_S);
    video.play();
    // The shot form table is below the video, so bring the video back into view.
    video.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  if (session?.status === "FAILED") {
    return (
      <section className="panel message">
        <h2>Couldn't process {session.original_filename}</h2>
        {session.error_message && <p className="detail">{session.error_message}</p>}
        <p>Check that the clip plays on your device, then upload it again.</p>
      </section>
    );
  }
  if (failed) {
    return (
      <section className="panel message">
        <h2>Couldn't reach the server</h2>
        <p>Check your connection and try again. Nothing was lost.</p>
      </section>
    );
  }
  if (upload || (session && (session.status !== "COMPLETED" || !session.video_url))) {
    return (
      <section className="panel working">
        <CourtScene />
        <JobProgress
          filename={upload ? upload.name : session!.original_filename}
          upload={upload}
          progress={session?.progress ?? null}
        />
      </section>
    );
  }
  if (!session) {
    return (
      <section className="panel welcome">
        <img src={curryShooting} alt="Stephen Curry shooting, seen from behind" />
        <div>
          <h2>See your makes, your misses, and how your form held up.</h2>
          <ol className="steps">
            <li>Upload a clip of you shooting, filmed from behind.</li>
            <li>CourtIQ finds each shot and calls it a make or a miss. This takes a few minutes.</li>
            <li>Watch it back, jump to any shot, and see your form numbers.</li>
          </ol>
          {uploadButton}
          {hasHistory && <p className="detail">Or pick a past session below.</p>}
        </div>
      </section>
    );
  }

  const attempts = session.makes + session.misses;
  const pickedShot = picked?.sessionId === session.id
    ? session.shots.find((shot) => shot.shot_number === picked.shotNumber)
    : undefined;
  return (
    <>
      <section className="panel viewer">
        <div className="stage">
          <video
            key={session.id}
            ref={videoRef}
            src={session.video_url ?? undefined}
            controls
            autoPlay
            playsInline
            onLoadedMetadata={(event) => setDuration(event.currentTarget.duration)}
            onTimeUpdate={(event) => setTime(event.currentTarget.currentTime)}
          />
          <ShotTape
            shots={session.shots}
            duration={duration}
            time={time}
            picked={pickedShot?.shot_number ?? null}
            onJump={jumpTo}
          />
        </div>

        <aside className="shots">
          <h2>{session.original_filename}</h2>
          <p className="detail">{formatDate(session.created_at)}</p>
          {attempts > 0 && (
            <p className="score">
              <b>{session.makes}</b> of {attempts} made
              <span>{Math.round((100 * session.makes) / attempts)}%</span>
            </p>
          )}

          {session.shots.length === 0 ? (
            <p className="empty">No shots found in this clip. CourtIQ needs to see both the ball and the hoop.</p>
          ) : (
            <ol>
              {session.shots.map((shot) => (
                <li key={shot.shot_number}>
                  <button
                    type="button"
                    className={shot.shot_number === pickedShot?.shot_number ? "picked" : undefined}
                    onClick={() => jumpTo(shot)}
                  >
                    <span className="detail">{shot.shot_number}</span>
                    <span className={shot.result === "MAKE" ? "make" : "miss"}>{shot.result === "MAKE" ? "Make" : "Miss"}</span>
                    <span className="time">{formatTime(shot.timestamp_s)}</span>
                  </button>
                </li>
              ))}
            </ol>
          )}
        </aside>
      </section>
      {pickedShot && <FormPictures shot={pickedShot} />}
      <FormTable session={session} onJump={jumpTo} picked={pickedShot?.shot_number ?? null} />
    </>
  );
}
