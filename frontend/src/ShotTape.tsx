import { formatTime } from "./format";
import type { Shot } from "./types";

type Props = {
  shots: Shot[];
  // The video's length and where it is playing now, both in seconds.
  duration: number;
  time: number;
  // The shot number that is picked, or null.
  picked: number | null;
  onJump: (shot: Shot) => void;
};

// The whole clip as one line. Each shot sits at the moment it happened: a filled green dot
// for a make, a red ring for a miss. The thin white bar is where the video is playing.
export default function ShotTape({ shots, duration, time, picked, onJump }: Props) {
  if (duration <= 0 || shots.length === 0) return null;
  const at = (seconds: number) => `${Math.min(100, (100 * seconds) / duration)}%`;

  return (
    <div className="tape">
      <div className="tape-line">
        <div className="tape-playhead" style={{ left: at(time) }} />
        {shots.map((shot) => {
          const result = shot.result === "MAKE" ? "make" : "miss";
          return (
            <button
              key={shot.shot_number}
              type="button"
              className={`tape-mark tape-${result}` + (shot.shot_number === picked ? " picked" : "")}
              style={{ left: at(shot.timestamp_s) }}
              aria-label={`Shot ${shot.shot_number}, ${result}, at ${formatTime(shot.timestamp_s)}`}
              title={`Shot ${shot.shot_number}: ${result} at ${formatTime(shot.timestamp_s)}`}
              onClick={() => onJump(shot)}
            />
          );
        })}
      </div>
      <div className="tape-ends detail">
        <span>0:00</span>
        <span>{formatTime(duration)}</span>
      </div>
    </div>
  );
}
