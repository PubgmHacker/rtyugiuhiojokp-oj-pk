import { useMemo } from "react";
import type { AdminStats } from "../../lib/admin";

interface Props {
  stats: AdminStats | null;
  /** Первая загрузка: пустой график в этот момент ещё не «Нет данных». */
  loading?: boolean;
}

export default function RegistrationsChart({ stats, loading = false }: Props) {
  const chartData = stats?.registrations_chart || [];
  const maxCount = useMemo(() => Math.max(...chartData.map((d) => d.count), 1), [chartData]);
  const width = 600;
  const height = 200;
  const padding = 40;
  const barWidth = (width - padding * 2) / Math.max(chartData.length, 1);

  if (!chartData.length) {
    return (
      <div className="bg-surface rounded-2xl p-6">
        <h3 className="font-semibold mb-4">Регистрации (14 дней)</h3>
        {loading ? (
          <div className="h-48 bg-bg rounded-xl animate-pulse" />
        ) : (
          <div className="h-48 flex items-center justify-center text-text-muted">Нет данных</div>
        )}
      </div>
    );
  }

  const points = chartData.map((d, i) => ({
    x: padding + i * barWidth + barWidth / 2,
    y: height - padding - (d.count / maxCount) * (height - padding * 2),
    ...d,
  }));

  const pathD = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`)
    .join(" ");

  const areaD = `${pathD} L ${points[points.length - 1].x} ${height - padding} L ${points[0].x} ${height - padding} Z`;

  return (
    <div className="bg-surface rounded-2xl p-6">
      <h3 className="font-semibold mb-4">Регистрации (14 дней)</h3>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto">
        <defs>
          <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-accent)" stopOpacity="0.4" />
            <stop offset="100%" stopColor="var(--color-accent)" stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Grid lines */}
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <line
            key={t}
            x1={padding}
            y1={padding + t * (height - padding * 2)}
            x2={width - padding}
            y2={padding + t * (height - padding * 2)}
            stroke="rgba(255,255,255,0.05)"
            strokeWidth="1"
          />
        ))}

        {/* Area */}
        <path d={areaD} fill="url(#areaGrad)" />

        {/* Line */}
        <path d={pathD} fill="none" stroke="var(--color-accent)" strokeWidth="2.5" />

        {/* Points + labels */}
        {points.map((p, i) => (
          <g key={i}>
            <circle cx={p.x} cy={p.y} r="4" fill="var(--color-accent)" />
            {p.count > 0 && (
              <text x={p.x} y={p.y - 10} textAnchor="middle" className="fill-text text-[10px]">
                {p.count}
              </text>
            )}
          </g>
        ))}

        {/* X-axis labels (every 2 days) */}
        {points.map((p, i) =>
          i % 2 === 0 ? (
            <text key={i} x={p.x} y={height - 12} textAnchor="middle" className="fill-text-muted text-[10px]">
              {new Date(p.date).getDate()}
            </text>
          ) : null
        )}
      </svg>
    </div>
  );
}
