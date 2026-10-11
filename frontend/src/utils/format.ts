/** "10–15 min", "1 h–1 h 15 min"; waits are rough, so never show seconds. */
export function formatMinutes(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}

export function formatWaitRange([min, max]: [number, number]): string {
  if (max <= 0) return "No wait";
  if (min >= 3600 || max >= 3600) return `${formatMinutes(min)}–${formatMinutes(max)}`;
  return `${Math.round(min / 60)}–${Math.round(max / 60)} min`;
}

export function initials(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

export function formatHour(hour: number, short = false): string {
  const suffix = hour < 12 ? (short ? "a" : " AM") : short ? "p" : " PM";
  const h = hour % 12 === 0 ? 12 : hour % 12;
  return `${h}${suffix}`;
}

/** "Alice", "Alice & Bob", "Alice, Bob & 2 unrecognized", "Camera: empty". */
export function formatCameraPeople(names: string[], unknownCount: number): string {
  if (names.length === 0 && unknownCount === 0) return "Camera: empty";
  const parts = [...names];
  if (unknownCount > 0) parts.push(unknownCount === 1 ? "1 unrecognized" : `${unknownCount} unrecognized`);
  if (parts.length === 1) return `On camera: ${parts[0]}`;
  return `On camera: ${parts.slice(0, -1).join(", ")} & ${parts[parts.length - 1]}`;
}
