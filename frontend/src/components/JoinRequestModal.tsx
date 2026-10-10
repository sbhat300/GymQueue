import type { QueueState } from "../types";

const ALREADY_STARTED_STATES: QueueState[] = ["active", "resting"];

export function JoinRequestModal({
  targetName,
  targetState,
  submitting,
  onConfirm,
  onCancel,
}: {
  targetName: string;
  targetState: QueueState;
  submitting: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const alreadyStarted = ALREADY_STARTED_STATES.includes(targetState);
  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(10,10,20,0.45)",
        backdropFilter: "blur(3px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 2000,
      }}
      onClick={onCancel}
    >
      <div className="card" style={{ maxWidth: 360, margin: 0 }} onClick={(e) => e.stopPropagation()}>
        <div className="card-title">Request to pair up?</div>
        <p className="card-subtitle">
          {alreadyStarted
            ? `${targetName} is already using this machine. If they accept, you'll jump in and work out together right away.`
            : `${targetName} will be asked to let you join their spot in the queue. You'll work out together when it's their turn.`}
        </p>
        <div className="btn-row" style={{ marginTop: 12 }}>
          <button className="btn btn-primary" onClick={onConfirm} disabled={submitting}>
            {submitting ? "Sending…" : "Send request"}
          </button>
          <button className="btn" onClick={onCancel} disabled={submitting}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
