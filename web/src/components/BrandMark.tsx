import { useId } from "react";
import { motion, useReducedMotion } from "framer-motion";

/**
 * Знак марки: два сплошных диска, в пересечении — свет.
 *
 * У каждого человека в продукте свой детерминированный цвет — аура
 * (lib/aura.ts). Знак: два залитых диска сходятся, пересечение — жёсткая
 * белая линза. Без колец и без soft-glow.
 *
 * Геометрия повторяет tools/brandmark.py (источник правды для PIL и
 * SVG-носителей): R = 24 при холсте 100, смещения ±13.92 / ∓8.64.
 *
 * `animated` — «дыхание»: диски медленно сходятся и расходятся, линза
 * растёт и тает. Уважает prefers-reduced-motion.
 */

const R = 24;
const DX = 13.92; // 0.580 R
const DY = 8.64; // 0.360 R
// Насколько диски сходятся в крайней точке дыхания
const ШАГ = 2.6;

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
  // id клипа уникальный на экземпляр: два знака на одной странице с общим
  // id резали бы друг друга чужим клипом. Двоеточия из useId убираем —
  // url(#:r0:) в SVG/CSS на части движков не резолвится
  const линза = `brand-lens-${useId().replace(/:/g, "")}`;

  const переход = {
    duration: 6,
    repeat: Infinity,
    repeatType: "mirror" as const,
    ease: "easeInOut" as const,
  };

  // Анимируются атрибуты cx/cy: линза задана клипом по кругу А, поэтому
  // круг внутри clipPath обязан двигаться синхронно с видимым — иначе
  // свет отстанет от пересечения.
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
        <clipPath id={линза}>
          <motion.circle cx={A.cx} cy={A.cy} r={R} animate={ходА} transition={переход} />
        </clipPath>
      </defs>
      <motion.circle
        cx={A.cx}
        cy={A.cy}
        r={R}
        fill="var(--color-accent)"
        animate={ходА}
        transition={переход}
      />
      <motion.circle
        cx={B.cx}
        cy={B.cy}
        r={R}
        fill="var(--color-mark-b)"
        animate={ходБ}
        transition={переход}
      />
      <motion.circle
        cx={B.cx}
        cy={B.cy}
        r={R}
        fill="var(--color-text)"
        clipPath={`url(#${линза})`}
        animate={ходБ}
        transition={переход}
      />
    </svg>
  );
}
