import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listCampuses } from "../api/campuses";
import type { Campus } from "../types";

export function HomePage() {
  const [campuses, setCampuses] = useState<Campus[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listCampuses()
      .then(setCampuses)
      .catch(() => setError("Couldn't load campuses"));
  }, []);

  return (
    <div className="page">
      <h1>Campuses</h1>
      {error && <div className="error-text">{error}</div>}
      {!campuses && !error && <div className="muted">Loading…</div>}
      {campuses?.length === 0 && <div className="empty-state">No campuses yet.</div>}
      {campuses?.map((campus) => (
        <Link key={campus.id} to={`/campuses/${campus.id}`} className="card card-link">
          <div className="card-title">{campus.name}</div>
        </Link>
      ))}
    </div>
  );
}
