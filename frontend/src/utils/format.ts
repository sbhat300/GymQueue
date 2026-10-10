/** "~12 min", "~1 h 5 min"; waits are estimates, so never show seconds. */
export function formatWait(seconds: number): string {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `~${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `~${h} h ${m} min` : `~${h} h`;
}

export function formatHour(hour: number, short = false): string {
  const suffix = hour < 12 ? (short ? "a" : " AM") : short ? "p" : " PM";
  const h = hour % 12 === 0 ? 12 : hour % 12;
  return `${h}${suffix}`;
}

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
