import { Link, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ToastStack } from "./ToastStack";
import { initials } from "../utils/format";

export function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  function handleLogout() {
    logout();
    navigate("/login");
  }

  return (
    <>
      <div className="topbar">
        <Link to="/" className="brand">
          <span className="brand-mark" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <circle cx="3" cy="8" r="2" fill="currentColor" opacity="0.55" />
              <circle cx="8" cy="8" r="2.4" fill="currentColor" opacity="0.8" />
              <circle cx="13.2" cy="8" r="2.8" fill="currentColor" />
            </svg>
          </span>
          <span className="brand-name">GymQueue</span>
        </Link>
        {user && (
          <div className="topbar-user">
            <span className="avatar avatar-sm" aria-hidden="true">
              {initials(user.display_name ?? user.netid)}
            </span>
            <span>{user.display_name ?? user.netid}</span>
            <button className="btn btn-sm btn-ghost" onClick={handleLogout}>
              Log out
            </button>
          </div>
        )}
      </div>
      <Outlet />
      <ToastStack />
    </>
  );
}
