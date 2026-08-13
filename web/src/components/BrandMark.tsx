import { useId } from "react";

/**
 * Знак марки: факел рассвета с вложенным сердцем.
 *
 * Иерархия как у Мимолёта (внешняя форма → сердце), своя геометрия:
 * снаружи пламя, внутри сердце negative space. Без отдельного глифа.
 * Геометрия повторяет tools/brandmark.py. Плоский, статичный.
 */

/** Пламя + сердце (evenodd). viewBox 100×100. */
const ФАКЕЛ_СЕРДЦЕ =
  "M 47.548,89.418 C 28.618,76.798 22.759,56.967 29.520,38.939 C 34.928,25.418 43.041,13.700 50.252,6.038 C 52.956,17.306 54.759,27.221 56.562,34.432 C 61.069,24.066 66.477,12.799 72.336,9.193 C 73.688,21.813 70.984,36.235 69.181,47.953 C 72.336,61.474 66.477,74.995 57.463,84.911 C 52.055,90.319 49.351,91.221 47.548,89.418 Z M 49.116,40.316 C 42.505,29.860 35.294,34.668 36.496,41.879 C 36.496,47.888 43.707,52.095 49.116,55.099 C 54.524,52.095 61.735,47.888 61.735,41.879 C 62.937,34.668 55.726,29.860 49.116,40.316 Z";

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
  const grad = `bm-dawn-${uid}`;

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
        <linearGradient id={grad} x1="28" y1="8" x2="58" y2="90" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#ff7a1a" />
          <stop offset="45%" stopColor="var(--color-accent)" />
          <stop offset="100%" stopColor="#b81648" />
        </linearGradient>
      </defs>
      <path d={ФАКЕЛ_СЕРДЦЕ} fillRule="evenodd" fill={`url(#${grad})`} />
    </svg>
  );
}
