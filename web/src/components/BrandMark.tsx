import { useId } from "react";
import { motion, useReducedMotion } from "framer-motion";

/**
 * Знак марки: две ауры, в пересечении — свет.
 *
 * У каждого человека в продукте свой детерминированный цвет — аура
 * (lib/aura.ts). Знак строится из той же идеи: два круга-ауры разных
 * оттенков перекрываются, и место пересечения загорается. Мэтч — это
 * пересечение двух людей; у знака ровно этот смысл.
 *
 * Геометрия повторяет tools/brandmark.py (источник правды для PIL и
 * SVG-носителей): R = 25 при холсте 100, смещения центров ±11 / ∓7.15.
 *
 * `animated` — «дыхание»: круги медленно сходятся и расходятся, линза
 * пересечения растёт и тает. Уважает prefers-reduced-motion.
 */

const R = 25;
const DX = 11;
const DY = 7.15;
// Насколько круги сходятся в крайней точке дыхания
const ШАГ = 3.2;

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
    ? { cx: [A.cx, A.cx + ШАГ], cy: [A.cy, A.cy - ШАГ * 0.65] }
    : undefined;
  const ходБ = дышит
    ? { cx: [B.cx, B.cx - ШАГ], cy: [B.cy, B.cy + ШАГ * 0.65] }
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
