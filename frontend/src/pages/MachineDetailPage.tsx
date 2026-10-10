import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getMachine } from "../api/machines";
import { getQueue, joinQueue, leaveQueue } from "../api/queue";
import { createJoinRequest } from "../api/joinRequests";
import { getMachineStats } from "../api/stats";
import { useAuth } from "../context/AuthContext";
import { useNotifications } from "../context/NotificationContext";
import { ApiError } from "../api/client";
import type { Machine, MachineStats, QueueEntry, QueueState, WsEvent } from "../types";
import { QueueEntryRow } from "../components/QueueEntryRow";
import { CheckInPanel } from "../components/CheckInPanel";
import { RestControls } from "../components/RestControls";
import { JoinRequestModal } from "../components/JoinRequestModal";
import { BusyTimesChart } from "../components/BusyTimesChart";
import { formatWaitRange } from "../utils/format";

const STATS_REFRESH_MS = 30_000;

const REFRESH_EVENT_TYPES = new Set([
  "queue_updated",
  "your_turn",
  "checked_in",
  "rest_started",
  "rest_expired",
  "rest_returned",
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
  const [stats, setStats] = useState<MachineStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState(false);
  const [joinRequestTarget, setJoinRequestTarget] = useState<{ entryId: string; name: string; state: QueueState } | null>(
    null
  );

  const refresh = useCallback(() => {
    if (!machineId) return;
    getQueue(machineId).then(setEntries).catch(() => setError("Couldn't load the queue"));
    // stats are a nice-to-have: keep showing the last ones if a refresh fails
    getMachineStats(machineId).then(setStats).catch(() => {});
  }, [machineId]);

  useEffect(() => {
    const interval = setInterval(refresh, STATS_REFRESH_MS); // waits tick down even when nothing changes
    return () => clearInterval(interval);
  }, [refresh]);

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

      {stats && <RightNow stats={stats} myEntry={myEntry} />}

      {myEntry?.state === "grace" && <CheckInPanel entry={myEntry} />}

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

      {myEntry && (myEntry.state === "active" || myEntry.state === "resting") && (
        <p className="muted" style={{ marginTop: -8, marginBottom: 12 }}>
          Walking away from the camera wraps up your turn within about 30 seconds - no need to leave manually.
        </p>
      )}

      <div className="btn-row" style={{ marginBottom: 20 }}>
        {!myEntry && (
          <button className="btn btn-primary" onClick={handleJoin} disabled={actionPending}>
            Join queue
          </button>
        )}
        {myEntry && (myEntry.state === "waiting" || myEntry.state === "grace") && (
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
            estimatedWaitSeconds={stats?.entry_wait_seconds[entry.id]}
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

      {stats && (
        <>
          <h3 style={{ marginTop: 24 }}>Busy today</h3>
          <BusyTimesChart
            hours={stats.busy_today}
            localHour={stats.local_hour}
            includesDemoData={stats.includes_demo_data}
          />
        </>
      )}

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

function RightNow({ stats, myEntry }: { stats: MachineStats; myEntry: QueueEntry | null }) {
  const myWait = myEntry ? stats.entry_wait_seconds[myEntry.id] : undefined;
  let waitLabel = "Wait if you join";
  let waitValue = formatWaitRange(stats.estimated_wait_seconds);
  if (myWait !== undefined) {
    waitLabel = "Your wait";
    waitValue = myWait[1] <= 0 ? "Up next" : formatWaitRange(myWait);
  } else if (myEntry) {
    waitLabel = "Your turn";
    waitValue = "Now";
  }

  return (
    <div className="stat-row">
      <div className="stat">
        <div className="stat-label">Right now</div>
        <div className="stat-value">{stats.in_use ? "In use" : "Free"}</div>
        {stats.people_on_camera !== null && (
          <div className="stat-note">
            Camera: {stats.people_on_camera === 1 ? "1 person" : `${stats.people_on_camera} people`}
          </div>
        )}
      </div>
      <div className="stat">
        <div className="stat-label">In line</div>
        <div className="stat-value">{stats.queue_length}</div>
        <div className="stat-note">{stats.people_in_queue} in queue incl. partners</div>
      </div>
      <div className="stat">
        <div className="stat-label">{waitLabel}</div>
        <div className="stat-value">{waitValue}</div>
        <div className="stat-note">
          {formatWaitRange(stats.turn_seconds)} per turn; partners share a turn
        </div>
      </div>
    </div>
  );
}
