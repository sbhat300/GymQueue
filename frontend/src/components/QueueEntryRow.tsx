import type { QueueEntry } from "../types";
import { formatWait } from "../utils/format";

function stateLabel(entry: QueueEntry): string {
  if (entry.state === "grace") {
    return entry.grace_reason === "turn_start" ? "awaiting check-in" : "wrapping up";
  }
  return entry.state;
}

export function QueueEntryRow({
  entry,
  currentUserId,
  onRequestJoin,
  estimatedWaitSeconds,
}: {
  entry: QueueEntry;
  currentUserId?: string;
  onRequestJoin?: () => void;
  estimatedWaitSeconds?: number;
}) {
  const isMe = entry.users.some((u) => u.id === currentUserId);
  return (
    <div
      className={`queue-entry ${isMe ? "is-me" : ""}`}
      onClick={onRequestJoin}
      style={onRequestJoin ? { cursor: "pointer" } : undefined}
    >
      <div>
        <div className="queue-entry-users">
          {entry.users
            .map((u) => (u.id === currentUserId ? `${u.display_name} (you)` : u.display_name))
            .join(" & ")}
        </div>
        {entry.rest_count > 0 && (
          <div className="card-subtitle">
            {entry.rest_count} rest{entry.rest_count > 1 ? "s" : ""} used
          </div>
        )}
        {onRequestJoin && <div className="card-subtitle">Tap to request to pair up</div>}
      </div>
      <div className="card-row-end">
        <span className={`badge badge-${entry.state}`}>{stateLabel(entry)}</span>
        {estimatedWaitSeconds !== undefined && (
          <div className="wait-chip" style={{ marginTop: 4 }}>
            {estimatedWaitSeconds < 60 ? "up next" : `${formatWait(estimatedWaitSeconds)} wait`}
          </div>
        )}
      </div>
    </div>
  );
}
