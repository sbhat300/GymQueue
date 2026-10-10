import { useEffect, useState } from "react";

export function useCountdown(deadline: string | null): number {
  const [secondsLeft, setSecondsLeft] = useState<number>(() => computeSecondsLeft(deadline));

  useEffect(() => {
    setSecondsLeft(computeSecondsLeft(deadline));
    if (!deadline) return;
    const interval = setInterval(() => {
      setSecondsLeft(computeSecondsLeft(deadline));
    }, 1000);
    return () => clearInterval(interval);
  }, [deadline]);

  return secondsLeft;
}

function computeSecondsLeft(deadline: string | null): number {
  if (!deadline) return 0;
  const diffMs = new Date(deadline).getTime() - Date.now();
  return Math.max(0, Math.round(diffMs / 1000));
}
