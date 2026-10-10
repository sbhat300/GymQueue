import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export function RequireAuth() {
  const { user, loading } = useAuth();
  if (loading) return <div className="page muted">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <Outlet />;
}

export function RequireOnboarded() {
  const { user } = useAuth();
  if (user && !user.onboarding_complete) return <Navigate to="/setup-name" replace />;
  return <Outlet />;
}
