import { useEffect, useRef, useState } from "react";
import type { BusyHour } from "../types";
import { formatHour } from "../utils/format";

const PLOT_HEIGHT = 140;
const AXIS_HEIGHT = 22;
const LEFT_GUTTER = 34;
const MAX_BAR = 24;
const RADIUS = 2;
const DEFAULT_OPEN = 6;

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

function peopleLabel(n: number): string {
  return `${n} ${n === 1 ? "person" : "people"}`;
}

/** Average people in the machine's queue for each hour of today. */
export function BusyTimesChart({
  hours,
  localHour,
  includesDemoData,
}: {
  hours: BusyHour[];
  localHour: number;
  includesDemoData: boolean;
}) {
  const [hovered, setHovered] = useState<number | null>(null);
  const [plotRef, width] = useWidth<HTMLDivElement>();

  const withData = hours.filter((h) => h.people !== null);
  const first = Math.min(DEFAULT_OPEN, ...withData.map((h) => h.hour));
  const last = Math.max(localHour, ...withData.map((h) => h.hour));
  const cells = hours.slice(first, last + 1);
  const busiest = withData.reduce<BusyHour | null>((a, h) => (a && a.people! >= h.people! ? a : h), null);
  const yMax = Math.max(2, Math.ceil(busiest?.people ?? 0));
  const ticks = yMax % 2 === 0 ? [yMax / 2, yMax] : [yMax];

  const plotWidth = Math.max(0, width - LEFT_GUTTER);
  const band = cells.length ? plotWidth / cells.length : 0;
  const barWidth = Math.max(2, Math.min(MAX_BAR, band - 6));
  const y = (v: number) => PLOT_HEIGHT - (v / yMax) * PLOT_HEIGHT;
  const hoveredCell = hovered === null ? null : hours[hovered];

  return (
    <div className="busy-chart">
      <div className="busy-headline">
        {busiest && busiest.people! > 0
          ? `Busiest so far: ${formatHour(busiest.hour)} (avg ${peopleLabel(busiest.people!)} in line)`
          : "Quiet so far today"}
      </div>

      <div className="busy-plot" ref={plotRef} onPointerLeave={() => setHovered(null)}>
        {width > 0 && (
          <svg width={width} height={PLOT_HEIGHT + AXIS_HEIGHT} role="img" aria-label="People in the queue by hour today">
            {[0, ...ticks].map((v) => (
              <g key={v}>
                <line className="busy-grid" x1={LEFT_GUTTER} x2={width} y1={y(v) + 0.5} y2={y(v) + 0.5} />
                {v > 0 && (
                  <text className="busy-axis" x={LEFT_GUTTER - 6} y={y(v) + 4} textAnchor="end">
                    {v}
                  </text>
                )}
              </g>
            ))}
            {cells.map((cell, i) => {
              const cx = LEFT_GUTTER + band * i + band / 2;
              return (
                <g key={cell.hour}>
                  {cell.people !== null && cell.people > 0 && (
                    <path
                      className={`busy-bar ${cell.hour === localHour ? "is-now" : ""} ${hovered === cell.hour ? "is-hovered" : ""}`}
                      d={barPath(cx - barWidth / 2, barWidth, y(cell.people), PLOT_HEIGHT)}
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
                      cell.people === null
                        ? `${formatHour(cell.hour)}: no data`
                        : `${formatHour(cell.hour)}: ${peopleLabel(cell.people)} in line on average`
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
              top: (hoveredCell.people === null ? PLOT_HEIGHT / 2 : y(hoveredCell.people)) - 8,
              left: Math.min(Math.max(LEFT_GUTTER + band * (hoveredCell.hour - first) + band / 2, 70), width - 70),
            }}
          >
            <strong>{hoveredCell.people === null ? "No data" : peopleLabel(hoveredCell.people)}</strong>
            <span>
              in line around {formatHour(hoveredCell.hour)}
              {hoveredCell.hour === localHour ? " (now)" : ""}
            </span>
          </div>
        )}
        {withData.length === 0 && <div className="busy-empty muted">No data yet today</div>}
      </div>

      <p className="card-subtitle busy-footnote">
        Average number of people in the queue each hour today. Partners working in together count individually.
        {includesDemoData && " Includes sample data."}
      </p>

      <details className="busy-table">
        <summary>Show as table</summary>
        <table>
          <thead>
            <tr>
              <th>Hour</th>
              <th>Avg. people in line</th>
            </tr>
          </thead>
          <tbody>
            {cells.map((cell) => (
              <tr key={cell.hour}>
                <td>{formatHour(cell.hour)}</td>
                <td>{cell.people === null ? "–" : cell.people}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
