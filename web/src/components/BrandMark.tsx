import { useId } from "react";
import { motion, useReducedMotion } from "framer-motion";

/**
 * Знак марки: две стеклянные линзы, в пересечении — каустика мэтча.
 *
 * У каждого человека в продукте свой детерминированный цвет — аура
 * (lib/aura.ts). Знак: два объёмных диска сходятся, пересечение —
 * светящаяся линза (не плоский Venn).
 *
 * Геометрия повторяет tools/brandmark.py (источник правды для PIL и
 * SVG-носителей): R = 24 при холсте 100, смещения ±13.44 / ∓8.40.
 *
 * `animated` — «дыхание»: диски медленно сходятся и расходятся, линза
 * растёт и тает. Уважает prefers-reduced-motion.
 */

const R = 24;
const DX = 13.44; // 0.560 R
const DY = 8.4; // 0.350 R
const ШАГ = 2.4;

const A = { cx: 50 - DX, cy: 50 + DY };
const B = { cx: 50 + DX, cy: 50 - DY };

export default function BrandMark({
  size = 64,
  animated = false,
  className = "",
}: {
  size?: number;
  animated?: boolean;
  className?: string;
}) {
  const тихо = useReducedMotion();
  const дышит = animated && !тихо;
  const uid = useId().replace(/:/g, "");
  const gradA = `bm-a-${uid}`;
  const gradB = `bm-b-${uid}`;
  const gradLens = `bm-lens-${uid}`;
  const clipLens = `bm-clip-${uid}`;
  const filt = `bm-f-${uid}`;
  const glowA = `bm-ga-${uid}`;
  const glowB = `bm-gb-${uid}`;

  const переход = {
    duration: 6,
    repeat: Infinity,
    repeatType: "mirror" as const,
    ease: "easeInOut" as const,
  };

  const ходА = дышит
    ? { cx: [A.cx, A.cx + ШАГ], cy: [A.cy, A.cy - ШАГ * 0.62] }
    : undefined;
  const ходБ = дышит
    ? { cx: [B.cx, B.cx - ШАГ], cy: [B.cy, B.cy + ШАГ * 0.62] }
    : undefined;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      fill="none"
      aria-hidden="true"
      className={className}
    >
      <defs>
        <radialGradient id={gradA} cx="32%" cy="28%" r="72%">
          <stop offset="0%" stopColor="#ffb0c8" />
          <stop offset="28%" stopColor="#ff5c8a" />
          <stop offset="58%" stopColor="var(--color-accent)" />
          <stop offset="100%" stopColor="#6b102e" />
        </radialGradient>
        <radialGradient id={gradB} cx="32%" cy="28%" r="72%">
          <stop offset="0%" stopColor="#ddd6fe" />
          <stop offset="28%" stopColor="#a78bfa" />
          <stop offset="58%" stopColor="var(--color-mark-b)" />
          <stop offset="100%" stopColor="#2e1065" />
        </radialGradient>
        <radialGradient id={gradLens} cx="50%" cy="42%" r="62%">
          <stop offset="0%" stopColor="#ffffff" stopOpacity="1" />
          <stop offset="40%" stopColor="#f5f3ff" stopOpacity="0.85" />
          <stop offset="78%" stopColor="#e9d5ff" stopOpacity="0.45" />
          <stop offset="100%" stopColor="#c084fc" stopOpacity="0.15" />
        </radialGradient>
        <radialGradient id={glowA} cx="50%" cy="50%" r="50%">
          <stop offset="55%" stopColor="var(--color-accent)" stopOpacity="0.45" />
          <stop offset="100%" stopColor="var(--color-accent)" stopOpacity="0" />
        </radialGradient>
        <radialGradient id={glowB} cx="50%" cy="50%" r="50%">
          <stop offset="55%" stopColor="var(--color-mark-b)" stopOpacity="0.45" />
          <stop offset="100%" stopColor="var(--color-mark-b)" stopOpacity="0" />
        </radialGradient>
        <filter id={filt} x="-35%" y="-35%" width="170%" height="170%">
          <feGaussianBlur in="SourceAlpha" stdDeviation="1.8" result="blur" />
          <feOffset dy="1.8" result="off" />
          <feFlood floodColor="#000000" floodOpacity="0.5" result="color" />
          <feComposite in="color" in2="off" operator="in" result="shadow" />
          <feMerge>
            <feMergeNode in="shadow" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <clipPath id={clipLens}>
          <motion.circle cx={A.cx} cy={A.cy} r={R} animate={ходА} transition={переход} />
        </clipPath>
      </defs>

      {/* Цветные ореолы */}
      <motion.circle
        cx={A.cx}
        cy={A.cy}
        r={R * 1.22}
        fill={`url(#${glowA})`}
        animate={ходА}
        transition={переход}
      />
      <motion.circle
        cx={B.cx}
        cy={B.cy}
        r={R * 1.22}
        fill={`url(#${glowB})`}
        animate={ходБ}
        transition={переход}
      />

      <g filter={`url(#${filt})`}>
        <motion.circle
          cx={A.cx}
          cy={A.cy}
          r={R}
          fill={`url(#${gradA})`}
          animate={ходА}
          transition={переход}
        />
        <motion.circle
          cx={B.cx}
          cy={B.cy}
          r={R}
          fill={`url(#${gradB})`}
          animate={ходБ}
          transition={переход}
        />
      </g>

      {/* Каустика пересечения */}
      <motion.circle
        cx={B.cx}
        cy={B.cy}
        r={R}
        fill={`url(#${gradLens})`}
        clipPath={`url(#${clipLens})`}
        animate={ходБ}
        transition={переход}
        opacity={0.9}
      />

      {/* Блики */}
      <motion.ellipse
        cx={A.cx - R * 0.32}
        cy={A.cy - R * 0.38}
        rx={R * 0.26}
        ry={R * 0.15}
        fill="#ffffff"
        opacity={0.78}
        animate={
          дышит
            ? {
                cx: [A.cx - R * 0.32, A.cx - R * 0.32 + ШАГ],
                cy: [A.cy - R * 0.38, A.cy - R * 0.38 - ШАГ * 0.62],
              }
            : undefined
        }
        transition={переход}
      />
      <motion.ellipse
        cx={B.cx - R * 0.32}
        cy={B.cy - R * 0.38}
        rx={R * 0.26}
        ry={R * 0.15}
        fill="#ffffff"
        opacity={0.78}
        animate={
          дышит
            ? {
                cx: [B.cx - R * 0.32, B.cx - R * 0.32 - ШАГ],
                cy: [B.cy - R * 0.38, B.cy - R * 0.38 + ШАГ * 0.62],
              }
            : undefined
        }
        transition={переход}
      />

      {/* Искра мэтча */}
      <circle cx={50} cy={50} r={2.8} fill="#ffffff" opacity={0.95} />
    </svg>
  );
}
