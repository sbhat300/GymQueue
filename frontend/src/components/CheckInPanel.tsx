import { useState } from "react";
import { checkIn } from "../api/queue";
import { useCountdown } from "../hooks/useCountdown";
import type { QueueEntry } from "../types";
import { ApiError } from "../api/client";

export function CheckInPanel({
  machineId,
  entry,
  onUpdated,
  onError,
}: {
  machineId: string;
  entry: QueueEntry;
  onUpdated: (entry: QueueEntry) => void;
  onError: (message: string) => void;
}) {
  const secondsLeft = useCountdown(entry.grace_deadline);
  const [submitting, setSubmitting] = useState(false);

  async function handleCheckIn() {
    setSubmitting(true);
    try {
      const updated = await checkIn(machineId, entry.id);
      onUpdated(updated);
    } catch (err) {
      onError(err instanceof ApiError ? err.message : "Couldn't check in");
    } finally {
      setSubmitting(false);
    }
  }

  const isResume = entry.grace_reason === "end_of_use";

  return (
    <div className="panel">
      <div className="panel-title">{isResume ? "Still working out?" : "It's your turn!"}</div>
      <p className="countdown">
        {secondsLeft > 0 ? `${secondsLeft}s left to check in` : "Grace period ending any moment…"}
      </p>
      <button className="btn btn-primary" onClick={handleCheckIn} disabled={submitting}>
        {isResume ? "I'm back — Resume" : "I'm here — Start"}
      </button>
    </div>
  );
}
