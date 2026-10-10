import type { RefObject } from "react";

const TICKS = 72;
const SIZE = 300;
const C = SIZE / 2;
// the circular camera view is sized in CSS (.faceid-video: inset 14% = radius 108 of 300)
const PROGRESS_R = 115;   // thin inner ring: "look straight" progress
const TICK_IN = 124;
const TICK_OUT = 142;
const POINTER_SPREAD = 28; // degrees either side of where the head points

// Screen direction (SVG angles: 0 = right, 90 = down) for each pose. The preview is mirrored,
// so turning to your LEFT moves toward the screen's left, like a mirror.
const SECTORS: Record<string, number> = { right: 0, down: 90, left: 180, up: 270 };
const SECTOR_HALF_WIDTH = 45;

function angleDiff(a: number, b: number): number {
  const d = Math.abs(((a - b) % 360) + 360) % 360;
  return d > 180 ? 360 - d : d;
}

/**
 * Face ID-style enrollment ring: the camera in a circle, ticks around it that turn green as
 * each head direction is captured, and a glow that follows where you're pointing your head.
 */
export function FaceIdScanner({
  videoRef,
  samples,
  samplesPerPose,
  step,
  done,
  pointer,
}: {
  videoRef: RefObject<HTMLVideoElement | null>;
  samples: Record<string, number>;
  samplesPerPose: number;
  step: string | null;
  done: boolean;
  /** where the head currently points, in screen space; null = facing the camera / unknown */
  pointer: { angle: number; strength: number } | null;
}) {
  const centerProgress = Math.min(1, (samples.center ?? 0) / samplesPerPose);
  const circumference = 2 * Math.PI * PROGRESS_R;

  const ticks = Array.from({ length: TICKS }, (_, i) => {
    const angle = (i * 360) / TICKS;
    const [pose, sectorAngle] = Object.entries(SECTORS).find(([, a]) => angleDiff(angle, a) <= SECTOR_HALF_WIDTH) ?? ["", 0];
    // fill each side from its middle outward as samples come in
    const fill = Math.min(1, (samples[pose] ?? 0) / samplesPerPose);
    const captured = done || (fill > 0 && angleDiff(angle, sectorAngle) <= fill * SECTOR_HALF_WIDTH + 0.01);
    const isTarget = !done && pose === step;
    const pointed =
      !done && pointer !== null && pointer.strength > 0.15 && angleDiff(angle, pointer.angle) <= POINTER_SPREAD;
    const rad = (angle * Math.PI) / 180;
    const len = pointed ? 8 : 0; // pointed ticks reach further out
    return {
      key: i,
      x1: C + TICK_IN * Math.cos(rad),
      y1: C + TICK_IN * Math.sin(rad),
      x2: C + (TICK_OUT + len) * Math.cos(rad),
      y2: C + (TICK_OUT + len) * Math.sin(rad),
      className: `faceid-tick${captured ? " is-captured" : ""}${pointed && !captured ? " is-pointed" : ""}${
        isTarget && !captured && !pointed ? " is-target" : ""
      }`,
    };
  });

  return (
    <div className={`faceid${done ? " is-done" : ""}`}>
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <video ref={videoRef} className="faceid-video" muted playsInline autoPlay />
      <svg className="faceid-ring" viewBox={`0 0 ${SIZE} ${SIZE}`} aria-hidden="true">
        <circle className="faceid-progress-track" cx={C} cy={C} r={PROGRESS_R} />
        <circle
          className="faceid-progress"
          cx={C}
          cy={C}
          r={PROGRESS_R}
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - (done ? 1 : centerProgress))}
          transform={`rotate(-90 ${C} ${C})`}
        />
        {ticks.map(({ key, className, ...line }) => (
          <line key={key} className={className} {...line} />
        ))}
      </svg>
      {done && (
        <svg className="faceid-check" viewBox="0 0 52 52" aria-hidden="true">
          <circle cx="26" cy="26" r="25" />
          <path d="M14 27 l8 8 l16 -17" />
        </svg>
      )}
    </div>
  );
}
