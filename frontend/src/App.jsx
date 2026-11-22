import { useEffect, useState } from "react";

const PENDING_STATUSES = new Set(["QUEUED", "PROCESSING"]);


export default function App() {
  const [session, setSession] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!session || !PENDING_STATUSES.has(session.status)) return undefined;

    let cancelled = false;
    let timer;

    async function refreshSession() {
      try {
        const response = await fetch(`/api/sessions/${session.id}`);
        if (!response.ok) throw new Error("Status request failed");

        const updatedSession = await response.json();
        if (cancelled) return;

        setSession(updatedSession);
        setFailed(updatedSession.status === "FAILED");
        if (PENDING_STATUSES.has(updatedSession.status)) {
          timer = window.setTimeout(refreshSession, 2000);
        }
      } catch {
        if (!cancelled) setFailed(true);
      }
    }

    timer = window.setTimeout(refreshSession, 1000);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [session]);

  async function selectVideo(event) {
    const file = event.target.files[0];
    event.target.value = "";
    if (!file) return;

    setUploading(true);
    setFailed(false);
    setSession(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch("/api/sessions", {
        method: "POST",
        body: formData,
      });
      if (!response.ok) throw new Error("Upload failed");
      setSession(await response.json());
    } catch {
      setFailed(true);
    } finally {
      setUploading(false);
    }
  }

  const working = uploading || PENDING_STATUSES.has(session?.status);
  const status = failed
    ? "FAILED"
    : uploading
      ? "UPLOADING"
      : session?.status || "READY";

  return (
    <main>
      <div className="controls">
        <label className={working ? "disabled" : ""}>
          SELECT VIDEO
          <input
            type="file"
            accept="video/mp4,video/quicktime,.mov,.mp4,.m4v"
            onChange={selectVideo}
            disabled={working}
          />
        </label>
        <span>{status}</span>
      </div>

      {session?.status === "COMPLETED" && (
        <video key={session.id} controls autoPlay playsInline>
          <source src={session.video_url} type="video/mp4" />
        </video>
      )}
    </main>
  );
}
