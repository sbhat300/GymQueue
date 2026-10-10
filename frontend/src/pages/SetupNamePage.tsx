import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../api/client";

export function SetupNamePage() {
  const { user, setProfile } = useAuth();
  const navigate = useNavigate();
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    // Only bounce on arrival if already onboarded (e.g. back button) - not a dependency
    // on `user`, since our own submit below also sets onboarding_complete and should
    // go to /setup-face, not race this effect to "/".
    if (user?.onboarding_complete) navigate("/", { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await setProfile(displayName.trim());
      navigate("/setup-face");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <h1>What should we call you?</h1>
      <p className="muted">This name shows up in queues so others know who's who.</p>
      <form className="form" onSubmit={handleSubmit}>
        <input
          className="input"
          placeholder="Display name"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          autoFocus
        />
        {error && <div className="error-text">{error}</div>}
        <button className="btn btn-primary" type="submit" disabled={submitting || !displayName.trim()}>
          {submitting ? "Saving…" : "Continue"}
        </button>
      </form>
    </div>
  );
}
