import JobProgress from "../JobProgress";
import type { Session, Shot } from "../types";
import Replay from "./Replay";

type Props = {
  session: Session | null;
  upload: { name: string; sent: number; total: number } | null;
  failed: boolean;
  // A shot picked on the Shot review tab, to play when the replay opens.
  request: { sessionId: string; shot: Shot; at: number } | null;
  hasHistory: boolean;
};

// The top of the dashboard: the open session's score, then its replay. While a clip is
// uploading or being processed, the progress takes the replay's place.
export default function Analysis({ session, upload, failed, request, hasHistory }: Props) {
  if (failed) {
    return (
      <section className="notice">
        <h2>Couldn't reach the server</h2>
        <p>Check your connection and try again. Nothing was lost.</p>
      </section>
    );
  }
  if (session?.status === "FAILED") {
    return (
      <section className="notice">
        <h2>Couldn't process {session.original_filename}</h2>
        {session.error_message && <p className="detail">{session.error_message}</p>}
        <p>Check that the clip plays on your device, then upload it again.</p>
      </section>
    );
  }
  if (upload || (session && (session.status !== "COMPLETED" || !session.video_url))) {
    return (
      <section className="working">
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
      <section className="notice">
        <h2>{hasHistory ? "Pick a session above." : "Upload your first clip."}</h2>
        <ol className="steps">
          <li>Film yourself shooting from behind, so the ball and the hoop are both in the picture.</li>
          <li>CourtIQ finds each shot and calls it a make or a miss. This takes a few minutes.</li>
          <li>Watch it back here, step shot to shot, and see your form numbers.</li>
        </ol>
      </section>
    );
  }

  const attempts = session.makes + session.misses;
  return (
    <>
      <dl className="scoreboard">
        <div>
          <dt>Shot attempts</dt>
          <dd>{attempts}</dd>
        </div>
        <div>
          <dt><i className="key make" />Makes</dt>
          <dd>{session.makes}</dd>
        </div>
        <div>
          <dt><i className="key miss" />Misses</dt>
          <dd>{session.misses}</dd>
        </div>
        <div>
          <dt>Field goal %</dt>
          <dd>{attempts ? `${((100 * session.makes) / attempts).toFixed(1)}%` : "-"}</dd>
        </div>
      </dl>
      <Replay key={session.id} session={session} request={request} />
    </>
  );
}
