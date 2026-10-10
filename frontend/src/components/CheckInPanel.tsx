import { useCountdown } from "../hooks/useCountdown";
import type { QueueEntry } from "../types";

export function CheckInPanel({ entry }: { entry: QueueEntry }) {
  const secondsLeft = useCountdown(entry.grace_deadline);
  const isResume = entry.grace_reason === "end_of_use";

  return (
    <div className="ticket">
      <div className="panel-title">{isResume ? "Still working out?" : "It's your turn!"}</div>
      <p className="countdown">
        {secondsLeft > 0 ? `${secondsLeft}s left to check in` : "Grace period ending any moment…"}
      </p>
      <p className="muted" style={{ marginTop: -4 }}>
        {isResume
          ? "Step back into the camera's view and turn your head left and right - we'll resume your turn automatically."
          : "Step up to the machine and turn your head left and right - the camera checks you in automatically."}
      </p>
    </div>
  );
}
