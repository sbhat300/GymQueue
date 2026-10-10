import { useNotifications } from "../context/NotificationContext";

export function ToastStack() {
  const { toasts, dismissToast } = useNotifications();

  if (toasts.length === 0) return null;

  return (
    <div className="toast-stack">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast toast-${toast.variant}`}>
          <button className="toast-dismiss" onClick={() => dismissToast(toast.id)} aria-label="Dismiss">
            ×
          </button>
          <div className="toast-title">{toast.title}</div>
          {toast.body && <div className="toast-body">{toast.body}</div>}
          {toast.actions && (
            <div className="toast-actions">
              {toast.actions.map((action) => (
                <button key={action.label} className="btn btn-sm" onClick={action.onClick}>
                  {action.label}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
