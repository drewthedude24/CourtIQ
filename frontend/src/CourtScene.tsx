// The drawing on the progress panel: a shooter seen from behind, the way the
// clips are filmed, with the ball's path and the hoop. The shooter is drawn the way CourtIQ
// sees a person, as joints and the lines between them. The ball moves along the dotted path
// (.scene-ball in App.css).

// Where each joint is, in the drawing's own units (480 wide, 330 tall).
const J = {
  leftShoulder: [98, 146],
  rightShoulder: [154, 142],
  leftElbow: [82, 122],
  rightElbow: [170, 102],
  leftWrist: [102, 88],
  rightWrist: [178, 60],
  leftHip: [110, 222],
  rightHip: [146, 220],
  leftKnee: [100, 260],
  rightKnee: [156, 256],
  leftAnkle: [108, 298],
  rightAnkle: [146, 294],
} as const;

// Each bone joins two joints.
const BONES: [keyof typeof J, keyof typeof J][] = [
  ["leftShoulder", "rightShoulder"],
  ["leftShoulder", "leftElbow"],
  ["leftElbow", "leftWrist"],
  ["rightShoulder", "rightElbow"],
  ["rightElbow", "rightWrist"],
  ["leftShoulder", "leftHip"],
  ["rightShoulder", "rightHip"],
  ["leftHip", "rightHip"],
  ["leftHip", "leftKnee"],
  ["leftKnee", "leftAnkle"],
  ["rightHip", "rightKnee"],
  ["rightKnee", "rightAnkle"],
];

export default function CourtScene() {
  return (
    <svg className="scene" viewBox="0 0 480 330" role="img" aria-label="A shooter seen from behind, the path of the ball, and a hoop">
      {/* The court: the far line under the hoop and the line the shooter jumped from. */}
      <line className="scene-paint" x1="262" y1="262" x2="462" y2="262" />
      <line className="scene-paint" x1="60" y1="324" x2="200" y2="324" />

      {/* The hoop: pole, backboard with its square, rim and net. */}
      <line className="scene-paint" x1="362" y1="122" x2="362" y2="262" />
      <rect className="scene-board" x="300" y="40" width="124" height="80" />
      <rect className="scene-paint" x="342" y="74" width="40" height="30" />
      <path className="scene-net" d="M338 114 L349 148 M350 118 L356 150 M362 119 V150 M374 118 L368 150 M386 114 L375 148 M343 130 Q362 136 381 130 M349 148 Q362 152 375 148" />
      <ellipse className="scene-rim" cx="362" cy="112" rx="26" ry="7" />

      {/* Where the ball has been: one dot for each frame the tracker saw it. */}
      <path className="scene-path" d="M178 40 Q272 -62 362 104" />

      {/* The shooter. */}
      {BONES.map(([from, to]) => (
        <line key={from + to} className="scene-bone" x1={J[from][0]} y1={J[from][1]} x2={J[to][0]} y2={J[to][1]} />
      ))}
      <circle className="scene-head" cx="127" cy="112" r="16" />
      {Object.entries(J).map(([name, [x, y]]) => (
        <circle key={name} className="scene-joint" cx={x} cy={y} r="4" />
      ))}

      <circle className="scene-ball" r="14" />
    </svg>
  );
}
