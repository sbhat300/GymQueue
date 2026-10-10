import { Link, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ToastStack } from "./ToastStack";

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
        <Link to="/" className="topbar-title">
          GymQueue
        </Link>
        {user && (
          <div className="topbar-user">
            <span>{user.display_name ?? user.netid}</span>
            <button className="btn btn-sm" onClick={handleLogout}>
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
