import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { deleteMyFace } from "../api/vision";
import { ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext";

export function AccountPage() {
  const { user, refreshUser } = useAuth();
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleted, setDeleted] = useState(false);

  if (!user) return null;

  async function handleDelete() {
    setDeleting(true);
    setError(null);
    try {
      await deleteMyFace();
      await refreshUser();
      setDeleted(true);
      setConfirming(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't delete your face data");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="page">
      {user.face_enrolled && (
        <Link to="/" className="back-link">
          ← Home
        </Link>
      )}
      <h1>Account</h1>

      <div className="card">
        <div className="card-title">{user.display_name ?? user.netid}</div>
        <p className="card-subtitle">NetID: {user.netid}</p>
      </div>

      <h3 style={{ marginTop: 24 }}>Face data</h3>
      <div className="card">
        {deleted && (
          <p className="muted" style={{ marginTop: 0 }}>
            Your face data has been deleted. Scan again whenever you want to use the camera check-in.
          </p>
        )}
        <p className="card-subtitle" style={{ marginBottom: 12 }}>
          {user.face_enrolled
            ? "Your face is registered, so machines recognise you automatically."
            : "No face registered. You'll need a face scan before you can join a queue."}{" "}
          We store a numeric face signature, not photos, only on the gym's camera server, and use it only to
          recognise you at machines.
        </p>
        {error && <p className="error-text">{error}</p>}

        {!confirming ? (
          <div className="btn-row">
            <button className="btn btn-primary" onClick={() => navigate("/setup-face")}>
              {user.face_enrolled ? "Re-scan my face" : "Scan my face"}
            </button>
            {user.face_enrolled && (
              <button className="btn btn-danger" onClick={() => setConfirming(true)}>
                Delete my face data
              </button>
            )}
          </div>
        ) : (
          <div className="panel" style={{ marginBottom: 0 }}>
            <div className="panel-title">Delete your face data?</div>
            <p className="muted" style={{ marginTop: 0 }}>
              Machines will stop recognising you, and you'll need to scan again before joining a queue.
            </p>
            <div className="btn-row">
              <button className="btn btn-danger" onClick={handleDelete} disabled={deleting}>
                {deleting ? "Deleting…" : "Yes, delete it"}
              </button>
              <button className="btn" onClick={() => setConfirming(false)} disabled={deleting}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
