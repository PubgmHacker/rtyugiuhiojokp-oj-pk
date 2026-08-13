import { useId } from "react";

/**
 * Знак марки: nested torch r3-06.
 *
 * Снаружи пламя (оранж→малина), внутри тёмное гнездо с «ушками».
 * Без отдельного глифа и без крупного сердца. Геометрия = tools/brandmark.py.
 */

/** Пламя + гнездо (evenodd). viewBox 100×100. */
const ФАКЕЛ =
  "M 50.000,81.494 C 35.850,72.061 31.470,57.236 36.523,43.760 C 40.566,33.652 46.631,24.893 52.021,19.165 C 54.043,27.588 55.391,35.000 56.738,40.391 C 60.107,32.642 64.150,24.219 68.530,21.523 C 69.541,30.957 67.520,41.738 66.172,50.498 C 68.530,60.605 64.150,70.713 57.412,78.125 C 53.369,82.168 51.348,82.842 50.000,81.494 Z M 50.450,65.683 C 44.323,62.473 41.919,56.266 44.070,50.074 C 45.803,45.173 48.630,40.724 51.251,37.715 C 52.094,40.674 52.757,43.065 53.580,44.592 C 54.551,43.065 56.403,40.674 59.349,38.964 C 59.645,43.824 58.476,49.114 57.743,53.202 C 58.691,57.762 56.497,61.957 53.480,64.624 C 51.798,65.881 50.994,66.076 50.450,65.683 Z";

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
          <stop offset="0%" stopColor="var(--color-flame-start, #ff7a1a)" />
          <stop offset="45%" stopColor="var(--color-accent)" />
          <stop offset="100%" stopColor="var(--color-flame-end, #b81648)" />
        </linearGradient>
      </defs>
      <path d={ФАКЕЛ} fillRule="evenodd" fill={`url(#${grad})`} />
    </svg>
  );
}
