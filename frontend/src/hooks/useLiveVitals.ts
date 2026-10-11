import { useEffect, useState } from "react";
import { useNotifications } from "../context/NotificationContext";
import type { WsEvent } from "../types";

const LIVE_TIMEOUT_MS = 30_000; // readings arrive every ~15-20s; clear if a couple in a row are missed

export interface LiveVitals {
  machineId: string;
  exercise: string;
  hr: number;
  rr: number | null;
}

/**
 * Live-ish heart rate from a machine camera (Presage), for the signed-in user only.
 * Readings refresh every ~15-20s (clip upload + processing), not frame-by-frame, and are a
 * wellness estimate - not a medical reading. Clears once the set finishes or the camera
 * goes quiet for a while.
 */
export function useLiveVitals(): LiveVitals | null {
  const { addEventListener } = useNotifications();
  const [live, setLive] = useState<LiveVitals | null>(null);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const unsubscribe = addEventListener((event: WsEvent) => {
      if (event.type === "vitals_update") {
        const data = event.data as { machine_id?: string; exercise?: string; hr?: number; rr?: number | null };
        if (data.hr == null) return;
        setLive({ machineId: data.machine_id ?? "", exercise: data.exercise ?? "", hr: data.hr, rr: data.rr ?? null });
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => setLive(null), LIVE_TIMEOUT_MS);
      } else if (event.type === "workout_logged") {
        setLive(null);
        if (timer) clearTimeout(timer);
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
