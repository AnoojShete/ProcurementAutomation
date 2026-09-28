import { useMemo, useState } from "react";
import type { UsageHistoryEntry } from "@/types/api";

interface UsageTrendChartProps {
  data: UsageHistoryEntry[];
  thresholdSeats: number;
  totalSeats: number;
}

export function UsageTrendChart({ data, thresholdSeats, totalSeats }: UsageTrendChartProps) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  const { points, maxVal, minVal, pathD, areaD, thresholdY } = useMemo(() => {
    if (!data || data.length === 0) {
      return { points: [], maxVal: totalSeats, minVal: 0, pathD: "", areaD: "", thresholdY: 0 };
    }

    const counts = data.map((d) => d.active_seats);
    const max = Math.max(...counts, totalSeats, thresholdSeats, 1);
    const min = 0;

    const width = 800;
    const height = 220;
    const paddingLeft = 45;
    const paddingRight = 20;
    const paddingTop = 20;
    const paddingBottom = 35;

    const chartWidth = width - paddingLeft - paddingRight;
    const chartHeight = height - paddingTop - paddingBottom;

    const computedPoints = data.map((d, index) => {
      const x = paddingLeft + (index / Math.max(data.length - 1, 1)) * chartWidth;
      const y = paddingTop + chartHeight - ((d.active_seats - min) / (max - min)) * chartHeight;
      return { x, y, date: d.date, active_seats: d.active_seats };
    });

    const pD = computedPoints.reduce((acc, p, idx) => {
      return idx === 0 ? `M ${p.x},${p.y}` : `${acc} L ${p.x},${p.y}`;
    }, "");

    const first = computedPoints[0];
    const last = computedPoints[computedPoints.length - 1];
    const groundY = paddingTop + chartHeight;
    const aD = pD ? `${pD} L ${last.x},${groundY} L ${first.x},${groundY} Z` : "";

    const tY = paddingTop + chartHeight - ((thresholdSeats - min) / (max - min)) * chartHeight;

    return {
      points: computedPoints,
      maxVal: max,
      minVal: min,
      pathD: pD,
      areaD: aD,
      thresholdY: Math.max(paddingTop, Math.min(groundY, tY)),
    };
  }, [data, thresholdSeats, totalSeats]);

  if (!data || data.length === 0) {
    return (
      <div className="flex h-56 items-center justify-center text-sm text-slate-400">
        No login history recorded in the last 90 days.
      </div>
    );
  }

  const hoveredPoint = hoveredIndex !== null && points[hoveredIndex] ? points[hoveredIndex] : null;

  return (
    <div className="relative w-full">
      <div className="mb-2 flex flex-wrap items-center justify-between text-xs text-slate-500">
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-full bg-brand-600" />
            Active Seats
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-4 border-t-2 border-dashed border-rose-500" />
            Minimum Expected Usage ({thresholdSeats} seats)
          </span>
        </div>
        <span>Total Licensed: {totalSeats} seats</span>
      </div>

      <div className="relative overflow-hidden rounded-lg border border-slate-100 bg-white p-2">
        <svg
          viewBox="0 0 800 220"
          className="h-56 w-full overflow-visible"
          onMouseLeave={() => setHoveredIndex(null)}
        >
          <defs>
            <linearGradient id="usageGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#2563eb" stopOpacity="0.25" />
              <stop offset="100%" stopColor="#2563eb" stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {/* Grid lines */}
          {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
            const y = 20 + (220 - 55) * ratio;
            const val = Math.round(maxVal - (maxVal - minVal) * ratio);
            return (
              <g key={ratio}>
                <line x1="45" y1={y} x2="780" y2={y} stroke="#f1f5f9" strokeWidth="1" />
                <text x="38" y={y + 4} textAnchor="end" className="fill-slate-400 text-[10px]">
                  {val}
                </text>
              </g>
            );
          })}

          {/* Reference Line for threshold */}
          <line
            x1="45"
            y1={thresholdY}
            x2="780"
            y2={thresholdY}
            stroke="#f43f5e"
            strokeWidth="1.5"
            strokeDasharray="4 4"
          />

          {/* Area fill */}
          {areaD && <path d={areaD} fill="url(#usageGradient)" />}

          {/* Trend line */}
          {pathD && (
            <path
              d={pathD}
              fill="none"
              stroke="#2563eb"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}

          {/* Hover hit points */}
          {points.map((p, idx) => (
            <rect
              key={p.date}
              x={p.x - 4}
              y="0"
              width="8"
              height="220"
              fill="transparent"
              className="cursor-pointer"
              onMouseEnter={() => setHoveredIndex(idx)}
            />
          ))}

          {/* Hover highlight circle */}
          {hoveredPoint && (
            <g>
              <line
                x1={hoveredPoint.x}
                y1="20"
                x2={hoveredPoint.x}
                y2="185"
                stroke="#94a3b8"
                strokeWidth="1"
                strokeDasharray="2 2"
              />
              <circle
                cx={hoveredPoint.x}
                cy={hoveredPoint.y}
                r="5"
                fill="#2563eb"
                stroke="#ffffff"
                strokeWidth="2"
              />
            </g>
          )}

          {/* X Axis dates (sample 5 dates) */}
          {points.length > 0 &&
            [0, Math.floor(points.length * 0.25), Math.floor(points.length * 0.5), Math.floor(points.length * 0.75), points.length - 1].map((idx) => {
              const pt = points[idx];
              if (!pt) return null;
              return (
                <text
                  key={pt.date}
                  x={pt.x}
                  y="205"
                  textAnchor="middle"
                  className="fill-slate-400 text-[10px]"
                >
                  {pt.date.slice(5)}
                </text>
              );
            })}
        </svg>

        {/* Hover Tooltip */}
        {hoveredPoint && (
          <div
            className="pointer-events-none absolute -top-2 z-10 -translate-x-1/2 -translate-y-full rounded-md border border-slate-200 bg-slate-900 px-2.5 py-1.5 text-xs text-white shadow-lg"
            style={{
              left: `${(hoveredPoint.x / 800) * 100}%`,
              top: `${(hoveredPoint.y / 220) * 100}%`,
            }}
          >
            <div className="font-semibold">{hoveredPoint.date}</div>
            <div className="text-slate-300">
              Active Seats: <span className="font-bold text-white">{hoveredPoint.active_seats}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
