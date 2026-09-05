/**
 * Аура — цвет, выведенный из личности, а не выбранный в настройках.
 *
 * У каждого человека свой градиент, посчитанный из его id: кольцо
 * аватара, обводка карточки в колоде, кольцо истории. Смысл в узнавании —
 * в списках люди начинают различаться до того, как прочитано имя.
 *
 * Считаем на клиенте и не храним. Поле в базе означало бы миграцию, экран
 * выбора и модерацию — кто-нибудь непременно возьмёт цвет чужого бренда.
 * Хеш детерминированный, поэтому цвет один и тот же на всех устройствах.
 *
 * Палитра фиксированная — восемь пар из iOS-клиента Plink: свободный подбор
 * давал ауры, невидимые на тёмном фоне, и ауры, выжигающие глаз, а общая
 * палитра на оба продукта делает человека узнаваемым в обоих.
 */

export interface Aura {
  /** Основной тон, 0–359. */
  hue: number;
  /** Начало и конец градиента. */
  from: string;
  to: string;
  /** Кольцо аватара и историй. */
  ring: string;
  /** Полупрозрачная подложка — плашки, фон блока. */
  wash: string;
  /** Свечение под карточкой. */
  glow: string;
  /** Пара цветов личности «светлый → тёмный». */
  pair: readonly [string, string];
  /** Акцент — светлый цвет пары: кнопки и бейджи на лице анкеты. */
  accent: string;
  /** Фон заглушки-буквы: пара, притемнённая до читаемости белой буквы. */
  letter: string;
}

/**
 * Палитра личности — та же, что в iOS-клиенте Plink (PlinkAvatarPalette):
 * восемь пар «светлый → тёмный», индекс = FNV-1a от id по модулю 8.
 *
 * Одна палитра на оба продукта не случайна: человек, пришедший из знакомств
 * смотреть кино, должен узнавать свою букву и цвет, а не заводить новую
 * «личность» в каждом приложении. Пары подобраны так, чтобы белая буква
 * читалась на любой из них и чтобы соседние индексы не были похожи.
 */
export const IDENTITY_PAIRS: readonly (readonly [string, string])[] = [
  ["#5B6CFF", "#8E4BE0"],
  ["#FF5C7A", "#C0326B"],
  ["#FFA23A", "#E0632B"],
  ["#22C1A4", "#0E7C8A"],
  ["#A05CFF", "#5C2FD6"],
  ["#35A8FF", "#2C63E0"],
  ["#7BD44A", "#2E9E5B"],
  ["#E24BC8", "#7A1F9E"],
];

const КОДИРОВЩИК = typeof TextEncoder !== "undefined" ? new TextEncoder() : null;

/**
 * FNV-1a 32 бит по байтам UTF-8 строки в нижнем регистре без пробелов по
 * краям — байт в байт как в Plink, поэтому у одного человека один индекс
 * на телефоне и в мини-аппе.
 */
export function хеш(seed: string): number {
  const норм = seed.trim().toLowerCase();
  const байты = КОДИРОВЩИК
    ? КОДИРОВЩИК.encode(норм)
    : Uint8Array.from(норм, (c) => c.charCodeAt(0) & 0xff);
  let h = 0x811c9dc5;
  for (let i = 0; i < байты.length; i++) {
    h ^= байты[i];
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/** Индекс пары для семени: 0–7. */
export function identityIndex(seed: string): number {
  return хеш(seed || "simp") % IDENTITY_PAIRS.length;
}

/** Пара цветов личности. */
export function identityPair(seed: string): readonly [string, string] {
  return IDENTITY_PAIRS[identityIndex(seed)];
}

function clamp01(x: number): number {
  return Math.min(1, Math.max(0, x));
}

function rgbToHex(r: number, g: number, b: number): string {
  const h = (c: number) =>
    Math.round(clamp01(c) * 255)
      .toString(16)
      .padStart(2, "0");
  return `#${h(r)}${h(g)}${h(b)}`;
}

/** Относительная яркость sRGB (WCAG). */
export function luminance(hex: string): number {
  const rgb = hexToRgb(hex) ?? [0, 0, 0];
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2]);
}

/**
 * Тот же тон, но с яркостью в коридоре 0.14–0.31 (как `legible()` в Plink):
 * ниже — буква сливается с тёмным фоном приложения, выше — белая буква
 * теряет контраст. Тон и насыщенность не трогаем, только светлоту.
 *
 * Яркость нелинейна по каналам (гамма sRGB), поэтому нужную долю подмеса
 * ищем делением отрезка, а не считаем по формуле: двенадцати шагов хватает
 * на точность лучше 0.001, а результат кэшируется вместе с аурой.
 */
export function legible(hex: string): string {
  const rgb = hexToRgb(hex);
  if (!rgb) return hex;
  const [r, g, b] = rgb.map((c) => c / 255) as [number, number, number];
  const L = luminance(hex);
  if (L >= 0.14 && L <= 0.31) return hex;

  // Смешение с белым (вверх) или чёрным (вниз) на долю t
  const target = L > 0.31 ? 0.31 : 0.14;
  const towards = L > 0.31 ? 0 : 1;
  const mix = (t: number) =>
    rgbToHex(r + (towards - r) * t, g + (towards - g) * t, b + (towards - b) * t);
  let lo = 0;
  let hi = 1;
  for (let i = 0; i < 12; i++) {
    const mid = (lo + hi) / 2;
    const Lm = luminance(mix(mid));
    // Ярче цели — при затемнении идём дальше, при осветлении откатываемся
    if ((Lm > target) === (towards === 0)) lo = mid;
    else hi = mid;
  }
  return mix((lo + hi) / 2);
}

/** Тон (0–359) для совместимости с прежней «аурой по оттенку». */
function hueOf(hex: string): number {
  const rgb = hexToRgb(hex);
  if (!rgb) return 0;
  const [r, g, b] = rgb.map((c) => c / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const d = max - min;
  if (d === 0) return 0;
  let h: number;
  if (max === r) h = ((g - b) / d) % 6;
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  return Math.round(((h * 60) % 360 + 360) % 360);
}

const КЭШ = new Map<number, Aura>();

/**
 * Аура по индексу палитры.
 *
 * Кэш ключуем индексом, а не семенем: аура целиком выводится из пары, пар
 * восемь, и большего кэшу знать незачем. Раньше ключом был id, и карта
 * росла на каждого встреченного человека — на ленте это тысячи длинных
 * строк ради восьми разных значений.
 */
export function auraAt(index: number): Aura {
  const i = ((index % IDENTITY_PAIRS.length) + IDENTITY_PAIRS.length) % IDENTITY_PAIRS.length;
  const готовая = КЭШ.get(i);
  if (готовая) return готовая;

  const [a, b] = IDENTITY_PAIRS[i];
  const la = legible(a);
  const lb = legible(b);
  const rgbA = hexToRgb(a) ?? [168, 85, 247];
  const rgba = (alpha: number) => `rgb(${rgbA[0]} ${rgbA[1]} ${rgbA[2]} / ${alpha})`;

  const aura: Aura = {
    hue: hueOf(a),
    pair: [a, b],
    accent: a,
    from: a,
    to: b,
    ring: `conic-gradient(from 140deg, ${a}, ${b}, ${a})`,
    wash: rgba(0.14),
    glow: `0 12px 40px -14px ${rgba(0.55)}`,
    letter: `linear-gradient(145deg, ${la}, ${lb})`,
  };

  КЭШ.set(i, aura);
  return aura;
}

/**
 * Аура по строке-семени (обычно user_id).
 */
export function auraOf(seed: string): Aura {
  return auraAt(identityIndex(seed));
}

/**
 * Раскладка непохожих цветов на короткий список.
 *
 * Для людей столкновение пар безобидно: двое случайных с одной буквой и
 * одним цветом в разных концах ленты друг с другом никак не соседствуют.
 * Для каталога комнат — наоборот: все шесть лежат подряд в одной карте, и
 * FNV по slug'ам честно выдавал три одинаково оранжевых кружка. Со стороны
 * это читается не как «цвет от личности», а как «цвет наугад».
 *
 * Индекс по-прежнему берётся из семени; занятый — сдвигается к ближайшему
 * свободному вперёд по кругу. Порядок списка входит в результат, поэтому
 * зовём это только там, где список стабилен и короток. Список длиннее
 * палитры снова начинает повторяться — восьми пар хватает ровно на восемь
 * непохожих соседей, и притворяться иначе было бы враньём.
 */
export function spreadIdentityIndexes(seeds: readonly string[]): number[] {
  const занято = new Set<number>();
  return seeds.map((seed) => {
    const старт = identityIndex(seed);
    for (let шаг = 0; шаг < IDENTITY_PAIRS.length; шаг++) {
      const i = (старт + шаг) % IDENTITY_PAIRS.length;
      if (!занято.has(i)) {
        занято.add(i);
        return i;
      }
    }
    занято.clear();
    занято.add(старт);
    return старт;
  });
}

/**
 * Стиль заглушки-буквы для аватара без фото: градиент пары личности,
 * притемнённый до читаемости белой буквы. Одна функция на все списки —
 * чтобы у человека без фото везде была одна и та же плашка.
 */
export function letterAvatarStyle(seed: string | null | undefined): {
  background: string;
  color: string;
} {
  return { background: auraOf(seed || "simp").letter, color: "#ffffff" };
}

/** То же, но по готовому индексу — для списков, разложенных `spreadIdentityIndexes`. */
export function letterAvatarStyleAt(index: number): { background: string; color: string } {
  return { background: auraAt(index).letter, color: "#ffffff" };
}

/**
 * Цвет текста, читаемый на данном фоне.
 *
 * Нужен для пользовательских цветов пузыря в чате: человек имеет право
 * выбрать светло-жёлтый, и белый текст на нём исчезает. Порог 0.62 по
 * относительной яркости — подобран по фактической читаемости, формальный
 * WCAG-контраст здесь избыточен, текст крупный и жирный.
 */
export function readableOn(hex: string | null | undefined): string {
  const rgb = hexToRgb(hex);
  if (!rgb) return "#ffffff";
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  const L = 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2]);
  return L > 0.62 ? "#0d1017" : "#ffffff";
}

export function hexToRgb(hex: string | null | undefined): [number, number, number] | null {
  if (!hex || !/^#[0-9a-fA-F]{6}$/.test(hex)) return null;
  return [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
}

/** Тот же цвет с заданной прозрачностью — для подложек под пузырём. */
export function withAlpha(hex: string | null | undefined, alpha: number): string | null {
  const rgb = hexToRgb(hex);
  if (!rgb) return null;
  return `rgb(${rgb[0]} ${rgb[1]} ${rgb[2]} / ${alpha})`;
}
