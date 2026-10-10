import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { listMachines } from "../api/machines";
import { getCampusMachineStats } from "../api/stats";
import type { Machine, MachineNow } from "../types";
import { formatWaitRange } from "../utils/format";

const STATS_REFRESH_MS = 30_000;

function availability(now: MachineNow | undefined): { primary: string; secondary?: string } | null {
  if (!now) return null;
  if (!now.in_use && now.queue_length === 0) return { primary: "Free now" };
  return {
    primary: `${formatWaitRange(now.estimated_wait_seconds)} wait`,
    secondary: `${now.people_in_queue} ${now.people_in_queue === 1 ? "person" : "people"} in queue`,
  };
}

export function MachineListPage() {
  const { campusId } = useParams<{ campusId: string }>();
  const [machines, setMachines] = useState<Machine[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<Record<string, MachineNow>>({});

  useEffect(() => {
    if (!campusId) return;
    listMachines(campusId)
      .then(setMachines)
      .catch(() => setError("Couldn't load machines"));
  }, [campusId]);

  useEffect(() => {
    if (!campusId) return;
    const load = () =>
      getCampusMachineStats(campusId)
        .then((rows) => setStats(Object.fromEntries(rows.map((r) => [r.machine_id, r]))))
        .catch(() => {});
    load();
    const interval = setInterval(load, STATS_REFRESH_MS);
    return () => clearInterval(interval);
  }, [campusId]);

  return (
    <div className="page">
      <Link to="/" className="back-link">
        ← Campuses
      </Link>
      <h1>Machines</h1>
      {error && <div className="error-text">{error}</div>}
      {!machines && !error && <div className="muted">Loading…</div>}
      {machines?.length === 0 && <div className="empty-state">No machines at this campus.</div>}
      {machines?.map((machine) => {
        const status = availability(stats[machine.id]);
        return (
          <Link key={machine.id} to={`/machines/${machine.id}`} className="card card-link card-row">
            <div>
              <div className="card-title">{machine.name}</div>
              <p className="card-subtitle">{machine.category.replace("_", " ")}</p>
            </div>
            {status && (
              <div className="card-row-end">
                <div className={`card-title ${status.primary === "Free now" ? "status-free" : "status-text"}`}>
                  {status.primary}
                </div>
                {status.secondary && <p className="card-subtitle">{status.secondary}</p>}
              </div>
            )}
          </Link>
        );
      })}
    </div>
  );
}
