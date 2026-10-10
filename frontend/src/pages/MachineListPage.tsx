import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { listMachines } from "../api/machines";
import type { Machine } from "../types";

export function MachineListPage() {
  const { campusId } = useParams<{ campusId: string }>();
  const [machines, setMachines] = useState<Machine[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!campusId) return;
    listMachines(campusId)
      .then(setMachines)
      .catch(() => setError("Couldn't load machines"));
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
      {machines?.map((machine) => (
        <Link key={machine.id} to={`/machines/${machine.id}`} className="card card-link">
          <div className="card-title">{machine.name}</div>
          <p className="card-subtitle">{machine.category.replace("_", " ")}</p>
        </Link>
      ))}
    </div>
  );
}
