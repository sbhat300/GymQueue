import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getMachine } from "../api/machines";
import { finishTurn, getQueue, joinQueue, leaveQueue } from "../api/queue";
import { createJoinRequest } from "../api/joinRequests";
import { useAuth } from "../context/AuthContext";
import { useNotifications } from "../context/NotificationContext";
import { ApiError } from "../api/client";
import type { Machine, QueueEntry, QueueState, WsEvent } from "../types";
import { QueueEntryRow } from "../components/QueueEntryRow";
import { CheckInPanel } from "../components/CheckInPanel";
import { RestControls } from "../components/RestControls";
import { JoinRequestModal } from "../components/JoinRequestModal";

const REFRESH_EVENT_TYPES = new Set([
  "queue_updated",
  "your_turn",
  "checked_in",
  "rest_started",
  "rest_expired",
  "session_ended",
  "removed_from_queue",
]);

export function MachineDetailPage() {
  const { machineId: machineIdParam } = useParams<{ machineId: string }>();
  const machineId = machineIdParam as string;
  const { user } = useAuth();
  const { subscribeMachine, unsubscribeMachine, addEventListener, pushToast } = useNotifications();

  const [machine, setMachine] = useState<Machine | null>(null);
  const [entries, setEntries] = useState<QueueEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState(false);
  const [joinRequestTarget, setJoinRequestTarget] = useState<{ entryId: string; name: string; state: QueueState } | null>(
    null
  );

  const refresh = useCallback(() => {
    if (!machineId) return;
    getQueue(machineId).then(setEntries).catch(() => setError("Couldn't load the queue"));
  }, [machineId]);

  useEffect(() => {
    if (!machineId) return;
    getMachine(machineId)
      .then(setMachine)
      .catch(() => setError("Couldn't load machine details"));
    refresh();
  }, [machineId, refresh]);

  useEffect(() => {
    if (!machineId) return;
    subscribeMachine(machineId);
    const unsubscribe = addEventListener((event: WsEvent) => {
      const data = event.data as { machine_id?: string };
      if (data.machine_id === machineId && REFRESH_EVENT_TYPES.has(event.type)) {
        refresh();
      }
    });
    return () => {
      unsubscribe();
      unsubscribeMachine(machineId);
    };
  }, [machineId, subscribeMachine, unsubscribeMachine, addEventListener, refresh]);

  if (!machineId) return null;

  const myEntry = entries?.find((e) => e.users.some((u) => u.id === user?.id)) ?? null;

  async function runAction(fn: () => Promise<unknown>) {
    setActionPending(true);
    setError(null);
    try {
      await fn();
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setActionPending(false);
    }
  }

  function handleJoin() {
    runAction(() => joinQueue(machineId));
  }

  function handleLeave() {
    if (!myEntry) return;
    runAction(() => leaveQueue(machineId, myEntry.id));
  }

  function handleFinish() {
    if (!myEntry) return;
    runAction(() => finishTurn(machineId, myEntry.id));
  }

  async function confirmJoinRequest() {
    if (!joinRequestTarget) return;
    setActionPending(true);
    try {
      await createJoinRequest(machineId, joinRequestTarget.entryId);
      pushToast({ title: "Request sent", body: `${joinRequestTarget.name} will be notified.`, variant: "success" });
      setJoinRequestTarget(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't send request");
    } finally {
      setActionPending(false);
    }
  }

  return (
    <div className="page">
      <Link to={machine ? `/campuses/${machine.campus_id}` : "/"} className="back-link">
        ← Machines
      </Link>
      <h1>{machine?.name ?? "Machine"}</h1>
      {error && <div className="error-text" style={{ marginBottom: 12 }}>{error}</div>}

      {myEntry?.state === "grace" && (
        <CheckInPanel machineId={machineId} entry={myEntry} onUpdated={refresh} onError={setError} />
      )}

      {myEntry && (myEntry.state === "active" || myEntry.state === "resting") && machine && (
        <RestControls
          machineId={machineId}
          entry={myEntry}
          maxRests={machine.max_rests}
          onUpdated={refresh}
          onError={setError}
        />
      )}

      {myEntry && myEntry.state === "waiting" && (
        <div className="panel">
          <div className="panel-title">You're in the queue</div>
          <p className="muted">We'll notify you when it's your turn.</p>
        </div>
      )}

      <div className="btn-row" style={{ marginBottom: 20 }}>
        {!myEntry && (
          <button className="btn btn-primary" onClick={handleJoin} disabled={actionPending}>
            Join queue
          </button>
        )}
        {myEntry && (myEntry.state === "active" || myEntry.state === "resting") && (
          <button className="btn" onClick={handleFinish} disabled={actionPending}>
            Finish turn
          </button>
        )}
        {myEntry && (
          <button className="btn btn-danger" onClick={handleLeave} disabled={actionPending}>
            Leave queue
          </button>
        )}
      </div>

      <h3>Queue</h3>
      {!entries && <div className="muted">Loading…</div>}
      {entries?.length === 0 && <div className="empty-state">No one's in line. Be the first to join!</div>}
      {entries?.map((entry) => {
        const isMe = entry.users.some((u) => u.id === user?.id);
        const canRequestJoin = !myEntry && !isMe && entry.users.length === 1;
        return (
          <QueueEntryRow
            key={entry.id}
            entry={entry}
            currentUserId={user?.id}
            onRequestJoin={
              canRequestJoin
                ? () =>
                    setJoinRequestTarget({
                      entryId: entry.id,
                      name: entry.users[0].display_name,
                      state: entry.state,
                    })
                : undefined
            }
          />
        );
      })}

      {joinRequestTarget && (
        <JoinRequestModal
          targetName={joinRequestTarget.name}
          targetState={joinRequestTarget.state}
          submitting={actionPending}
          onConfirm={confirmJoinRequest}
          onCancel={() => setJoinRequestTarget(null)}
        />
      )}
    </div>
  );
}
