import { useEffect, useRef, useState } from "react";
import type { BusyCell } from "../types";
import { WEEKDAYS, formatHour } from "../utils/format";

const PLOT_HEIGHT = 140;
const AXIS_HEIGHT = 22;
const LEFT_GUTTER = 34;
const MAX_BAR = 24;
const RADIUS = 4;
const DEFAULT_OPEN = 6;
const DEFAULT_CLOSE = 22;

function busyWord(busy: number): string {
  if (busy < 0.3) return "not busy";
  if (busy < 0.6) return "a little busy";
  if (busy < 0.85) return "busy";
  return "as busy as it gets";
}

/** Column with a 4px rounded top, square at the baseline. */
function barPath(x: number, w: number, top: number, base: number): string {
  const r = Math.min(RADIUS, w / 2, base - top);
  return `M${x},${base} V${top + r} Q${x},${top} ${x + r},${top} H${x + w - r} Q${x + w},${top} ${x + w},${top + r} V${base} Z`;
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

export function BusyTimesChart({
  busyTimes,
  localWeekday,
  localHour,
  historyDays,
  includesDemoData,
  liveBusy,
}: {
  busyTimes: BusyCell[][];
  localWeekday: number;
  localHour: number;
  historyDays: number;
  includesDemoData: boolean;
  liveBusy: boolean; // machine in use or people waiting right now
}) {
  const [day, setDay] = useState(localWeekday);
  const [hovered, setHovered] = useState<number | null>(null);
  const [plotRef, width] = useWidth<HTMLDivElement>();

  // show the hours the gym actually has data for (across all days), so every day lines up
  const withData = busyTimes.flat().filter((c) => c.busy !== null).map((c) => c.hour);
  const first = withData.length ? Math.min(...withData) : DEFAULT_OPEN;
  const last = withData.length ? Math.max(...withData) : DEFAULT_CLOSE;
  const cells = busyTimes[day].slice(first, last + 1);
  const hasData = cells.some((c) => c.busy !== null);
  const isToday = day === localWeekday;
  const now = isToday ? busyTimes[day][localHour] : null;

  const plotWidth = Math.max(0, width - LEFT_GUTTER);
  const band = cells.length ? plotWidth / cells.length : 0;
  const barWidth = Math.max(2, Math.min(MAX_BAR, band - 6));
  const y = (v: number) => PLOT_HEIGHT - v * PLOT_HEIGHT;
  const hoveredCell = hovered === null ? null : busyTimes[day][hovered];

  let headline = `${WEEKDAYS[day]}s`;
  if (isToday && now?.busy != null && liveBusy && now.busy < 0.6) headline = "Live: busier than usual right now";
  else if (isToday && now?.busy != null && !liveBusy && now.busy >= 0.6) headline = "Live: quieter than usual right now";
  else if (isToday && now?.busy != null) headline = `Usually ${busyWord(now.busy)} around ${formatHour(localHour)}`;
  else if (isToday) headline = "Today";

  return (
    <div className="busy-chart">
      <div className="day-tabs" role="tablist" aria-label="Day of the week">
        {WEEKDAYS.map((name, i) => (
          <button
            key={name}
            role="tab"
            aria-selected={i === day}
            className={`day-tab ${i === day ? "is-selected" : ""}`}
            onClick={() => setDay(i)}
          >
            {name.slice(0, 3)}
          </button>
        ))}
      </div>

      <div className="busy-headline">{headline}</div>

      <div className="busy-plot" ref={plotRef} onPointerLeave={() => setHovered(null)}>
        {width > 0 && (
          <svg width={width} height={PLOT_HEIGHT + AXIS_HEIGHT} role="img" aria-label={`Busy times for ${WEEKDAYS[day]}`}>
            {[0, 0.5, 1].map((v) => (
              <g key={v}>
                <line className="busy-grid" x1={LEFT_GUTTER} x2={width} y1={y(v) + 0.5} y2={y(v) + 0.5} />
                {v > 0 && (
                  <text className="busy-axis" x={LEFT_GUTTER - 6} y={y(v) + 4} textAnchor="end">
                    {v * 100}%
                  </text>
                )}
              </g>
            ))}
            {cells.map((cell, i) => {
              const cx = LEFT_GUTTER + band * i + band / 2;
              const isNow = isToday && cell.hour === localHour;
              return (
                <g key={cell.hour}>
                  {cell.busy !== null && cell.busy > 0 && (
                    <path
                      className={`busy-bar ${isNow ? "is-now" : ""} ${hovered === cell.hour ? "is-hovered" : ""}`}
                      d={barPath(cx - barWidth / 2, barWidth, y(cell.busy), PLOT_HEIGHT)}
                    />
                  )}
                  {cell.hour % 3 === 0 && (
                    <text className="busy-axis" x={cx} y={PLOT_HEIGHT + 16} textAnchor="middle">
                      {formatHour(cell.hour, true)}
                    </text>
                  )}
                  {/* hit target: the whole column, not just the painted bar */}
                  <rect
                    className="busy-hit"
                    x={LEFT_GUTTER + band * i}
                    y={0}
                    width={band}
                    height={PLOT_HEIGHT}
                    tabIndex={0}
                    aria-label={
                      cell.busy === null
                        ? `${formatHour(cell.hour)}: no data`
                        : `${formatHour(cell.hour)}: ${Math.round(cell.busy * 100)}% busy`
                    }
                    onPointerEnter={() => setHovered(cell.hour)}
                    onFocus={() => setHovered(cell.hour)}
                    onBlur={() => setHovered(null)}
                  />
                </g>
              );
            })}
          </svg>
        )}
        {hoveredCell && width > 0 && (
          <div
            className="chart-tooltip"
            style={{
              // sit just above the hovered bar, not over the tabs
              top: (hoveredCell.busy === null ? PLOT_HEIGHT / 2 : y(hoveredCell.busy)) - 8,
              left: Math.min(
                Math.max(LEFT_GUTTER + band * (hoveredCell.hour - first) + band / 2, 70),
                width - 70
              ),
            }}
          >
            <strong>{hoveredCell.busy === null ? "No data" : `${Math.round(hoveredCell.busy * 100)}% busy`}</strong>
            <span>
              {WEEKDAYS[day].slice(0, 3)} {formatHour(hoveredCell.hour)}
              {hoveredCell.queue ? ` · ~${hoveredCell.queue} in line` : ""}
            </span>
          </div>
        )}
        {!hasData && <div className="busy-empty muted">No data for {WEEKDAYS[day]}s yet</div>}
      </div>

      <p className="card-subtitle busy-footnote">
        Share of time the machine is in use, from the queue and its camera over the last {Math.round(historyDays / 7)}{" "}
        weeks.{includesDemoData && " Includes sample data."}
      </p>

      <details className="busy-table">
        <summary>Show as table</summary>
        <table>
          <thead>
            <tr>
              <th>Hour</th>
              <th>Busy</th>
              <th>Avg. in line</th>
            </tr>
          </thead>
          <tbody>
            {cells.map((cell) => (
              <tr key={cell.hour}>
                <td>{formatHour(cell.hour)}</td>
                <td>{cell.busy === null ? "–" : `${Math.round(cell.busy * 100)}%`}</td>
                <td>{cell.queue === null ? "–" : cell.queue}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
