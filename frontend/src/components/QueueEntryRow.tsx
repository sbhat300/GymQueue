import type { QueueEntry } from "../types";
import { formatWaitRange, initials } from "../utils/format";

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
  estimatedWaitSeconds?: [number, number];
}) {
  const isMe = entry.users.some((u) => u.id === currentUserId);
  return (
    <div
      className={`queue-entry ${isMe ? "is-me" : ""}`}
      onClick={onRequestJoin}
      style={onRequestJoin ? { cursor: "pointer" } : undefined}
    >
      <div className="queue-entry-main">
        <div className="avatar-stack">
          {entry.users.map((u) => (
            <span key={u.id} className="avatar" aria-hidden="true">
              {initials(u.display_name)}
            </span>
          ))}
        </div>
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
      </div>
      <div className="card-row-end">
        <span className={`badge badge-${entry.state}`}>{stateLabel(entry)}</span>
        {estimatedWaitSeconds !== undefined && (
          <div className="wait-chip" style={{ marginTop: 4 }}>
            {estimatedWaitSeconds[1] <= 0 ? "up next" : `${formatWaitRange(estimatedWaitSeconds)} wait`}
          </div>
        )}
      </div>
    </div>
  );
}
