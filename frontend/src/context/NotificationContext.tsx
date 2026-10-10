import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { acceptJoinRequest, listIncomingJoinRequests, rejectJoinRequest } from "../api/joinRequests";
import { GymSocket } from "../ws/socket";
import type { WsEvent } from "../types";
import { useAuth } from "./AuthContext";

export interface Toast {
  id: string;
  title: string;
  body?: string;
  variant: "info" | "success" | "warning" | "error";
  sticky?: boolean;
  actions?: { label: string; onClick: () => void }[];
}

interface NotificationContextValue {
  toasts: Toast[];
  dismissToast: (id: string) => void;
  pushToast: (toast: Omit<Toast, "id">) => string;
  addEventListener: (fn: (event: WsEvent) => void) => () => void;
  subscribeMachine: (machineId: string) => void;
  unsubscribeMachine: (machineId: string) => void;
}

const NotificationContext = createContext<NotificationContextValue | null>(null);

let idCounter = 0;
function nextId() {
  idCounter += 1;
  return `toast-${idCounter}-${Date.now()}`;
}

export function NotificationProvider({ children }: { children: ReactNode }) {
  const { token } = useAuth();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const socketRef = useRef<GymSocket | null>(null);

  function pushToast(toast: Omit<Toast, "id">): string {
    const id = nextId();
    setToasts((prev) => [...prev, { ...toast, id }]);
    if (!toast.sticky) {
      setTimeout(() => dismissToast(id), 6000);
    }
    return id;
  }

  function dismissToast(id: string) {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }

  useEffect(() => {
    if (!token) {
      socketRef.current?.close();
      socketRef.current = null;
      return;
    }

    const socket = new GymSocket(token);
    socketRef.current = socket;

    listIncomingJoinRequests()
      .then((requests) => {
        for (const req of requests) {
          pushJoinRequestToast(req.id, req.requester_display_name);
        }
      })
      .catch(() => {
        // best-effort backlog fetch; ignore failures
      });

    const unsubscribe = socket.addListener((event) => handleEvent(event));
    return () => {
      unsubscribe();
      socket.close();
      socketRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  function pushJoinRequestToast(requestId: string, requesterName: string) {
    const toastId = nextId();
    setToasts((prev) => [
      ...prev,
      {
        id: toastId,
        title: "Partner request",
        body: `${requesterName} wants to join your queue slot.`,
        variant: "info",
        sticky: true,
        actions: [
          {
            label: "Accept",
            onClick: async () => {
              await acceptJoinRequest(requestId);
              dismissToast(toastId);
            },
          },
          {
            label: "Reject",
            onClick: async () => {
              await rejectJoinRequest(requestId);
              dismissToast(toastId);
            },
          },
        ],
      },
    ]);
  }

  function handleEvent(event: WsEvent) {
    switch (event.type) {
      case "your_turn": {
        const data = event.data as { machine_name?: string };
        pushToast({
          title: "It's your turn!",
          body: `${data.machine_name ?? "A machine"} is ready for you. Head over: the camera checks you in automatically.`,
          variant: "success",
        });
        break;
      }
      case "checked_in": {
        pushToast({ title: "Checked in", body: "You're on the machine. Have a good set!", variant: "success" });
        break;
      }
      case "removed_from_queue": {
        const data = event.data as { reason?: string };
        pushToast({
          title: "Removed from queue",
          body: data.reason === "grace_expired" ? "You didn't check in before the grace period ended." : "You left the queue.",
          variant: "warning",
        });
        break;
      }
      case "session_ended": {
        pushToast({ title: "Session ended", body: "Your turn on the machine has ended.", variant: "info" });
        break;
      }
      case "rest_expired": {
        pushToast({ title: "Rest period expired", body: "You didn't return in time — the machine is wrapping up your turn.", variant: "warning" });
        break;
      }
      case "not_your_machine": {
        const data = event.data as { machine_name?: string; reason?: string };
        const name = data.machine_name ?? "This machine";
        pushToast({
          title: "Not your turn",
          body:
            data.reason === "not_your_turn"
              ? `${name} isn't ready for you yet — someone else still has it.`
              : `You're not currently queued for ${name}. Join the queue in the app to use it.`,
          variant: "warning",
        });
        break;
      }
      case "join_request_received": {
        const data = event.data as { request_id: string; requester_display_name?: string };
        pushJoinRequestToast(data.request_id, data.requester_display_name ?? "Someone");
        break;
      }
      case "join_request_accepted": {
        pushToast({ title: "Request accepted", body: "You've been paired up — good luck!", variant: "success" });
        break;
      }
      case "join_request_rejected": {
        pushToast({ title: "Request declined", variant: "warning" });
        break;
      }
      default:
        break;
    }
  }

  function addEventListener(fn: (event: WsEvent) => void) {
    const socket = socketRef.current;
    if (!socket) return () => {};
    return socket.addListener(fn);
  }

  function subscribeMachine(machineId: string) {
    socketRef.current?.subscribe(machineId);
  }

  function unsubscribeMachine(machineId: string) {
    socketRef.current?.unsubscribe(machineId);
  }

  return (
    <NotificationContext.Provider
      value={{ toasts, dismissToast, pushToast, addEventListener, subscribeMachine, unsubscribeMachine }}
    >
      {children}
    </NotificationContext.Provider>
  );
}

export function useNotifications() {
  const ctx = useContext(NotificationContext);
  if (!ctx) throw new Error("useNotifications must be used within NotificationProvider");
  return ctx;
}
