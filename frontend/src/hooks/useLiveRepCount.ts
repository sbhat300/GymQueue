import { useEffect, useState } from "react";
import { useNotifications } from "../context/NotificationContext";
import type { WsEvent } from "../types";

const LIVE_TIMEOUT_MS = 20_000; // hide the live counter if the camera goes quiet

export interface LiveRepCount {
  machineId: string;
  machineName: string;
  exercise: string;
  reps: number;
}

/**
 * Live rep count from a machine camera, for the signed-in user only - the backend sends
 * "rep_counted" to that one user's socket, so this never shows anyone else's reps.
 * Clears once the set finishes ("workout_logged") or the camera goes quiet for a while.
 */
export function useLiveRepCount(onSetLogged?: () => void): LiveRepCount | null {
  const { addEventListener } = useNotifications();
  const [live, setLive] = useState<LiveRepCount | null>(null);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const unsubscribe = addEventListener((event: WsEvent) => {
      if (event.type === "rep_counted") {
        const data = event.data as { machine_id?: string; machine_name?: string; exercise?: string; reps?: number };
        setLive({
          machineId: data.machine_id ?? "",
          machineName: data.machine_name ?? "Machine",
          exercise: data.exercise ?? "",
          reps: data.reps ?? 0,
        });
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => setLive(null), LIVE_TIMEOUT_MS);
      } else if (event.type === "workout_logged") {
        setLive(null);
        onSetLogged?.();
      }
    });
    return () => {
      unsubscribe();
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [addEventListener]);

  return live;
}
