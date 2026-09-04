import { useId } from "react";

/**
 * Знак марки: nested torch r3-06.
 *
 * Снаружи пламя (оранж→малина), внутри тёмное гнездо с «ушками».
 * Без отдельного глифа и без сердца. Геометрия = tools/brandmark.py.
 */

/** Внешнее пламя. */
const ПЛАМЯ =
  "M 50.000,81.494 C 35.850,72.061 31.470,57.236 36.523,43.760 C 40.566,33.652 46.631,24.893 52.021,19.165 C 54.043,27.588 55.391,35.000 56.738,40.391 C 60.107,32.642 64.150,24.219 68.530,21.523 C 69.541,30.957 67.520,41.738 66.172,50.498 C 68.530,60.605 64.150,70.713 57.412,78.125 C 53.369,82.168 51.348,82.842 50.000,81.494 Z";

/** Тёмное гнездо внутри пламени — дырка по evenodd. */
const ГНЕЗДО =
  "M 50.391,66.523 C 44.320,62.477 42.441,56.117 44.609,50.336 C 46.344,46.000 48.945,42.242 51.258,39.785 C 52.000,42.200 52.600,44.200 53.350,45.500 C 54.200,44.200 55.800,42.200 58.340,40.797 C 58.773,44.844 57.906,49.469 57.328,53.227 C 58.340,57.563 56.461,61.898 53.570,65.078 C 51.836,66.812 50.969,67.102 50.391,66.523 Z";

export default function BrandMark({
  size = 64,
  animated: _animated = false,
  className = "",
  solid = false,
}: {
  size?: number;
  animated?: boolean;
  className?: string;
  /**
   * Только внешнее пламя, без гнезда. Мелким кеглем (значок серии в списке
   * чатов — 14px) дырка съедает середину, и знак читается смазанным пятном,
   * а не факелом. Крупнее 24px не включать: гнездо и есть марка.
   */
  solid?: boolean;
}) {
  const uid = useId().replace(/:/g, "");
  const grad = `bm-torch-${uid}`;

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
        <linearGradient id={grad} x1="36" y1="18" x2="60" y2="82" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#ff7a1a" />
          <stop offset="45%" stopColor="#ff2d6f" />
          <stop offset="100%" stopColor="#b81648" />
        </linearGradient>
      </defs>
      <path
        d={solid ? ПЛАМЯ : `${ПЛАМЯ} ${ГНЕЗДО}`}
        fillRule="evenodd"
        fill={`url(#${grad})`}
      />
    </svg>
  );
}
