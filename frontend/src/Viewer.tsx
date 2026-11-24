import { useRef, type ReactNode } from "react";
import FormTable from "./FormTable";
import { formatDate, formatTime } from "./format";
import type { Session } from "./types";

// Start playback a little before the detected moment, so you see the shot go up.
const LEAD_IN_S = 2;

type Props = {
  session: Session | null;
  uploading: boolean;
  failed: boolean;
};

function Message({ children }: { children: ReactNode }) {
  return <section className="placeholder">{children}</section>;
}

export default function Viewer({ session, uploading, failed }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);

  function jumpTo(seconds: number) {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = Math.max(0, seconds - LEAD_IN_S);
    video.play();
    // The shot form table is below the video, so bring the video back into view.
    video.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  if (session?.status === "FAILED") {
    return (
      <Message>
        <p>Couldn't process {session.original_filename}.</p>
        {session.error_message && <p className="detail">{session.error_message}</p>}
      </Message>
    );
  }
  if (failed) return <Message><p>Couldn't reach the server. Try again.</p></Message>;
  if (uploading) return <Message><p>Uploading…</p></Message>;
  if (!session) return <Message><p>Upload a clip, or pick a session below.</p></Message>;
  if (session.status !== "COMPLETED" || !session.video_url) {
    return (
      <Message>
        <p>Finding shots in {session.original_filename}.</p>
        <p className="detail">This takes a few minutes.</p>
      </Message>
    );
  }

  const attempts = session.makes + session.misses;
  return (
    <>
      <section className="viewer">
        <video key={session.id} ref={videoRef} src={session.video_url} controls autoPlay playsInline />

        <aside className="shots">
          <h2>{session.original_filename}</h2>
          <p className="detail">
            {formatDate(session.created_at)} · {session.makes} of {attempts} made
            {attempts > 0 && ` · ${Math.round((100 * session.makes) / attempts)}%`}
          </p>

          {session.shots.length === 0 ? (
            <p className="detail">No shots found in this clip.</p>
          ) : (
            <ol>
              {session.shots.map((shot) => (
                <li key={shot.shot_number}>
                  <button type="button" onClick={() => jumpTo(shot.timestamp_s)}>
                    <span className="detail">{shot.shot_number}</span>
                    <span className={shot.result === "MAKE" ? "make" : "miss"}>{shot.result}</span>
                    <span className="time">{formatTime(shot.timestamp_s)}</span>
                  </button>
                </li>
              ))}
            </ol>
          )}
        </aside>
      </section>
      <FormTable session={session} onJump={jumpTo} />
    </>
  );
}
