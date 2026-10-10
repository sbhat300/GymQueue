import { useState } from "react";
import { startRest } from "../api/queue";
import { useCountdown } from "../hooks/useCountdown";
import type { QueueEntry } from "../types";
import { ApiError } from "../api/client";

export function RestControls({
  machineId,
  entry,
  maxRests,
  onUpdated,
  onError,
}: {
  machineId: string;
  entry: QueueEntry;
  maxRests: number;
  onUpdated: (entry: QueueEntry) => void;
  onError: (message: string) => void;
}) {
  const [submitting, setSubmitting] = useState(false);
  const restSecondsLeft = useCountdown(entry.rest_deadline);

  async function handleStartRest() {
    setSubmitting(true);
    try {
      onUpdated(await startRest(machineId, entry.id));
    } catch (err) {
      onError(err instanceof ApiError ? err.message : "Couldn't start rest");
    } finally {
      setSubmitting(false);
    }
  }

  if (entry.state === "resting") {
    return (
      <div className="panel">
        <div className="panel-title">Resting</div>
        <p className="countdown">{restSecondsLeft}s left before your spot wraps up</p>
        <p className="muted" style={{ marginTop: -4 }}>
          Walk back into the camera's view and we'll resume your turn automatically.
        </p>
      </div>
    );
  }

  const restsUsed = entry.rest_count;
  const atCap = restsUsed >= maxRests;

  return (
    <div className="btn-row" style={{ marginBottom: 16 }}>
      <button className="btn" onClick={handleStartRest} disabled={submitting || atCap} title={atCap ? `Max ${maxRests} rests used` : undefined}>
        Start rest ({restsUsed}/{maxRests})
      </button>
    </div>
  );
}
