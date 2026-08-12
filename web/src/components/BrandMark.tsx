import { useId } from "react";

/**
 * Знак марки: одна искра мэтча, внутри — капля (душа).
 *
 * У каждого человека свой цвет — аура (lib/aura.ts). Мэтч — встреча
 * двух аур: градиент малины и фиолета на ОДНОЙ форме. Не венн и не
 * два шара: доминирует мягкая 4-лучевая искра, внутри — одна капля.
 * Вложенность как у Мимолёта («звезда → сердце»), своя геометрия.
 *
 * Геометрия повторяет tools/brandmark.py. Плоский, статичный.
 */

const ИСКРА =
  "M50 8C53 34 66 47 92 50C66 53 53 66 50 92C47 66 34 53 8 50C34 47 47 34 50 8Z";

/** Капля (soul): остриё сверху, округлое тело снизу — один контур. */
const КАПЛЯ =
  "M50 36C50 36 39.5 47 39.5 55.5C39.5 61.8 44.2 66.5 50 66.5C55.8 66.5 60.5 61.8 60.5 55.5C60.5 47 50 36 50 36Z";

export default function BrandMark({
  size = 64,
  animated: _animated = false,
  className = "",
}: {
  size?: number;
  /** Сохранён для совместимости; знак статичен. */
  animated?: boolean;
  className?: string;
}) {
  const uid = useId().replace(/:/g, "");
  const grad = `bm-spark-${uid}`;

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
        <linearGradient id={grad} x1="18" y1="18" x2="82" y2="82" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="var(--color-accent)" />
          <stop offset="100%" stopColor="var(--color-mark-b)" />
        </linearGradient>
      </defs>
      <path d={ИСКРА} fill={`url(#${grad})`} />
      <path d={КАПЛЯ} fill="#fafbfc" />
    </svg>
  );
}
