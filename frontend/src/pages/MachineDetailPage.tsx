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
import { formatCameraPeople, formatWaitRange } from "../utils/format";
import { useCountdown } from "../hooks/useCountdown";
import { useLiveRepCount } from "../hooks/useLiveRepCount";

const STATS_REFRESH_MS = 30_000;
const CAMERA_POLL_MS = 1_000; // while active here, so the off-camera countdown stays live

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

  const myEntry = entries?.find((e) => e.users.some((u) => u.id === user?.id)) ?? null;
  const isActiveHere = myEntry?.state === "active" || myEntry?.state === "resting";

  // "rep_counted" is pushed to this user's socket alone, so this only ever shows your own reps
  const live = useLiveRepCount(refresh);
  const liveHere = live && live.machineId === machineId ? live : null;

  useEffect(() => {
    // poll fast while you're actually on the machine, so the off-camera countdown
    // (driven by the camera's heartbeat) doesn't lag behind reality by up to 30s
    const ms = isActiveHere ? CAMERA_POLL_MS : STATS_REFRESH_MS;
    const interval = setInterval(refresh, ms);
    return () => clearInterval(interval);
  }, [refresh, isActiveHere]);

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

      {liveHere && (
        <div className="live-reps" aria-live="polite">
          <div className="live-reps-dot" aria-hidden="true" />
          <div>
            <div className="live-reps-label">Counting live</div>
            <div className="live-reps-count">
              {liveHere.reps} <span>{liveHere.reps === 1 ? "rep" : "reps"}</span>
            </div>
          </div>
        </div>
      )}

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
        <LeavingSoonBanner leavesAt={stats?.leaves_at ?? null} />
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
        const canRequestJoin = !myEntry && !isMe && entry.users.length < (machine?.max_group_size ?? 2);
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

function LeavingSoonBanner({ leavesAt }: { leavesAt: string | null }) {
  const secondsLeft = useCountdown(leavesAt);

  if (!leavesAt) {
    return (
      <p className="muted" style={{ marginTop: -8, marginBottom: 12 }}>
        Walking away from the camera wraps up your turn within about 30 seconds - no need to leave manually.
      </p>
    );
  }

  return (
    <p className="error-text" style={{ marginTop: -8, marginBottom: 12 }}>
      Camera can't see you - your turn ends in {secondsLeft}s unless you come back.
    </p>
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
        <div className={`stat-value ${stats.in_use ? "" : "status-free"}`}>{stats.in_use ? "In use" : "Free"}</div>
        {stats.camera_people != null && stats.camera_unknown_count != null && (
          <div className="stat-note">
            {formatCameraPeople(
              stats.camera_people.map((p) => p.display_name),
              stats.camera_unknown_count
            )}
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
          {formatWaitRange(stats.turn_seconds)}
          {stats.extra_seconds_per_partner != null &&
            ` per turn, +${Math.round(stats.extra_seconds_per_partner / 60)} min per person working in`}
        </div>
      </div>
    </div>
  );
}
