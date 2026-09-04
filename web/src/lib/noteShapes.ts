/**
 * Формы видеокружка.
 *
 * У мессенджеров кружок — всегда круг. У нас форму выбирает отправитель, и
 * она едет вместе с сообщением (media.shape): получатель видит то же самое.
 * Одна и та же геометрия служит и маской видео (CSS mask из SVG), и обводкой
 * с прогрессом воспроизведения (stroke-dasharray по pathLength=100), и
 * иконкой в выборе формы — иначе три копии одной звезды разъезжались бы.
 *
 * Пути заданы в квадрате 0..100 и заполняют его целиком: маска не должна
 * оставлять пустых полей, а видео под ней — object-fit: cover.
 */

export interface NoteShape {
  code: string;
  title: string;
  /** SVG path в системе координат 0..100. */
  d: string;
}

function polygon(points: Array<[number, number]>): string {
  return (
    points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(2)} ${y.toFixed(2)}`).join(" ") + " Z"
  );
}

function star(): string {
  const pts: Array<[number, number]> = [];
  const cx = 50, cy = 52, outer = 50, inner = 24;
  for (let i = 0; i < 10; i++) {
    const r = i % 2 === 0 ? outer : inner;
    const a = -Math.PI / 2 + (i * Math.PI) / 5;
    pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
  }
  return polygon(pts);
}

function hexagon(): string {
  const pts: Array<[number, number]> = [];
  for (let i = 0; i < 6; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / 3;
    pts.push([50 + 50 * Math.cos(a), 50 + 50 * Math.sin(a)]);
  }
  return polygon(pts);
}

/** Шесть лепестков дугами — цветок, а не шестерёнка. */
function flower(): string {
  const parts: string[] = [];
  const n = 6, cx = 50, cy = 50, rIn = 34, rOut = 50;
  for (let i = 0; i < n; i++) {
    const a0 = (i * 2 * Math.PI) / n - Math.PI / 2;
    const a1 = ((i + 1) * 2 * Math.PI) / n - Math.PI / 2;
    const x0 = cx + rIn * Math.cos(a0), y0 = cy + rIn * Math.sin(a0);
    const x1 = cx + rIn * Math.cos(a1), y1 = cy + rIn * Math.sin(a1);
    const am = (a0 + a1) / 2;
    const xm = cx + rOut * Math.cos(am), ym = cy + rOut * Math.sin(am);
    parts.push(`${i ? "L" : "M"}${x0.toFixed(2)} ${y0.toFixed(2)}`);
    parts.push(`Q${xm.toFixed(2)} ${ym.toFixed(2)} ${x1.toFixed(2)} ${y1.toFixed(2)}`);
  }
  return parts.join(" ") + " Z";
}

export const NOTE_SHAPES: NoteShape[] = [
  { code: "circle", title: "Круг", d: "M50 0A50 50 0 1 1 50 100A50 50 0 1 1 50 0Z" },
  {
    code: "squircle",
    title: "Квадрат",
    d: "M50 0C88 0 100 12 100 50C100 88 88 100 50 100C12 100 0 88 0 50C0 12 12 0 50 0Z",
  },
  {
    code: "heart",
    title: "Сердце",
    d: "M50 96C22 74 2 56 2 33C2 17 14 6 27 6C37 6 45 12 50 20C55 12 63 6 73 6C86 6 98 17 98 33C98 56 78 74 50 96Z",
  },
  { code: "star", title: "Звезда", d: star() },
  { code: "hexagon", title: "Шестигранник", d: hexagon() },
  {
    code: "tree",
    title: "Ёлка",
    d: "M50 2L72 30H62L82 58H70L94 86H58V98H42V86H6L30 58H18L38 30H28Z",
  },
  { code: "flower", title: "Цветок", d: flower() },
];

export const DEFAULT_NOTE_SHAPE = "circle";

export function noteShape(code?: string | null): NoteShape {
  return NOTE_SHAPES.find((s) => s.code === code) ?? NOTE_SHAPES[0];
}

/** CSS-маска по форме: одинаково для кружка в чате и предпросмотра записи. */
export function noteMaskStyle(code?: string | null): Record<string, string> {
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><path d='${noteShape(code).d}' fill='black'/></svg>`;
  const url = `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`;
  return {
    WebkitMaskImage: url,
    maskImage: url,
    WebkitMaskSize: "100% 100%",
    maskSize: "100% 100%",
    WebkitMaskRepeat: "no-repeat",
    maskRepeat: "no-repeat",
  };
}

const STORAGE_KEY = "sd_note_shape";

export function readPreferredShape(): string {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return NOTE_SHAPES.some((s) => s.code === v) ? (v as string) : DEFAULT_NOTE_SHAPE;
  } catch {
    return DEFAULT_NOTE_SHAPE;
  }
}

export function savePreferredShape(code: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, code);
  } catch {
    /* приватный режим — просто не запомним */
  }
}
