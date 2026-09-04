/**
 * Обложка анкеты — как в iOS-клиенте Plink (V4CoverStyle).
 *
 * У анкеты нет поля «обложка», и заводить его не нужно: обложка выводится
 * из того, что уже есть. Рамка из кейсов (`profile.decor`) задаёт один из
 * пресетов Plink — человек, купивший «Туманность», получает и туманную
 * обложку; без рамки обложка строится на паре цветов личности, той же, что
 * красит букву аватара. Так лицо анкеты всегда «своё», а не серое.
 *
 * Спецификация повторяет Plink: три стопа неба сверху вниз, одно мягкое
 * свечение со своим центром и силой, общий тёмный «пол» внизу и акцент,
 * которым красятся кнопка «Редактировать» и бейджи на лице.
 */
import { identityPair, хеш } from "./aura";

export interface CoverSpec {
  /** Три стопа градиента неба, сверху вниз. */
  sky: readonly [string, string, string];
  /** Цвет свечения. */
  glow: string;
  /** Центр свечения в долях ширины и высоты обложки. */
  glowCenter: readonly [number, number];
  /** Сила свечения 0–1. */
  glowStrength: number;
  /** Акцент лица анкеты. */
  accent: string;
  /** Имя пресета для подписи в оформлении. */
  title: string;
}

/**
 * Рамка из кейсов → пресет обложки. Ключи — коды `DECOR_STYLES`.
 * Сумерки/Полночь/Бархат — те же числа, что в Plink; «Заря» и «Затмение»
 * дорисованы в той же манере под тёплую и золотую рамки Симпа.
 */
export const COVER_PRESETS: Record<string, CoverSpec> = {
  dawn: {
    sky: ["#8C2231", "#5A1220", "#20070E"],
    glow: "#FF9A5A",
    glowCenter: [0.78, 0.1],
    glowStrength: 0.5,
    accent: "#FF7A52",
    title: "Заря",
  },
  frost: {
    sky: ["#16264F", "#0C1530", "#05070F"],
    glow: "#4FB4FF",
    glowCenter: [0.2, 0.08],
    glowStrength: 0.38,
    accent: "#4FB4FF",
    title: "Иней",
  },
  ember: {
    sky: ["#7A1F1F", "#B3412A", "#2A0A0A"],
    glow: "#FFB36B",
    glowCenter: [0.72, 0.1],
    glowStrength: 0.55,
    accent: "#FF6E5A",
    title: "Уголь",
  },
  nebula: {
    sky: ["#5D4BD4", "#9A55C4", "#3A1E52"],
    glow: "#FFB2C4",
    glowCenter: [0.85, 0.1],
    glowStrength: 0.55,
    accent: "#7C5CFF",
    title: "Туманность",
  },
  eclipse: {
    sky: ["#3A2E12", "#6B5320", "#14110A"],
    glow: "#FFE796",
    glowCenter: [0.25, 0.1],
    glowStrength: 0.6,
    accent: "#FFD166",
    title: "Затмение",
  },
};

/** Общий тёмный пол обложки — тот же, что у Plink. */
export const COVER_FLOOR = "#080615";

/** Тон пары, приглушённый к полу обложки на долю `t` (0–1). */
function приглушить(hex: string, t: number): string {
  return `color-mix(in srgb, ${hex} ${Math.round((1 - t) * 100)}%, ${COVER_FLOOR})`;
}

/**
 * Обложка по паре личности: без рамки, но и не серая — и не дешевле платных.
 *
 * Небо больше не прогоняется через `legible()`: коридор яркости 0.14–0.31
 * нужен заглушке-букве, а на обложке он схлопывал оба верхних стопа в одну
 * тёмную кашу — бесплатная обложка выглядела браком на фоне пресетов, хотя
 * рисовалась тем же кодом. Пара приглушается к общему полу, поэтому тон и
 * разница между стопами остаются. Центр и сила свечения берутся из того же
 * хеша: у двух человек с одной парой обложки всё равно разные, а не «та же
 * картинка другим цветом».
 */
export function identityCover(seed: string): CoverSpec {
  const [a, b] = identityPair(seed);
  const h = хеш(seed || "simp");
  return {
    sky: [приглушить(a, 0.22), приглушить(b, 0.36), COVER_FLOOR],
    glow: a,
    glowCenter: [(h >>> 3) % 2 ? 0.78 : 0.22, 0.06 + ((h >>> 5) % 3) * 0.05],
    glowStrength: 0.42 + ((h >>> 7) % 3) * 0.06,
    accent: a,
    title: "Своя",
  };
}

/** Обложка анкеты: пресет рамки, иначе — цвета личности. */
export function coverForProfile(profile: {
  id: string;
  decor?: string | null;
}): CoverSpec {
  const preset = profile.decor ? COVER_PRESETS[profile.decor] : undefined;
  return preset ?? identityCover(profile.id);
}

/** Слои фона обложки одной CSS-строкой: свечение поверх неба. */
export function coverBackground(spec: CoverSpec): string {
  const [cx, cy] = spec.glowCenter;
  const rgb = hexToRgbTriplet(spec.glow);
  const glow = `radial-gradient(circle at ${Math.round(cx * 100)}% ${Math.round(
    cy * 100
  )}%, rgb(${rgb} / ${spec.glowStrength}) 0%, rgb(${rgb} / 0) 62%)`;
  // Пол обложки: на тёмных темах — плотный тёмный низ (--cover-floor-mix: 100%),
  // на светлых тема снижает долю пола, чтобы обложка не уходила в чёрную полосу
  const floor = `color-mix(in srgb, ${spec.sky[2]} var(--cover-floor-mix, 100%), ${spec.sky[1]})`;
  const sky = `linear-gradient(180deg, ${spec.sky[0]} 0%, ${spec.sky[1]} 58%, ${floor} 100%)`;
  return `${glow}, ${sky}`;
}

function hexToRgbTriplet(hex: string): string {
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  if (!m) return "168 85 247";
  return `${parseInt(m[1], 16)} ${parseInt(m[2], 16)} ${parseInt(m[3], 16)}`;
}
