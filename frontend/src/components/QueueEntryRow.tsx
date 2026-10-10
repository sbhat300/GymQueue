import type { QueueEntry } from "../types";

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
}: {
  entry: QueueEntry;
  currentUserId?: string;
  onRequestJoin?: () => void;
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
      <span className={`badge badge-${entry.state}`}>{stateLabel(entry)}</span>
    </div>
  );
}
