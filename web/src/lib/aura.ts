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
 * Насыщенность и светлота зафиксированы: свободный подбор дал бы ауры,
 * невидимые на тёмном фоне, и ауры, выжигающие глаз. Меняется только тон.
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
}

/** FNV-1a: короткий, стабильный, без зависимостей. */
function хеш(seed: string): number {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

const КЭШ = new Map<string, Aura>();

/**
 * Аура по строке-семени (обычно user_id).
 *
 * Результат кэшируем: функция вызывается на каждый кадр перерисовки
 * списка, а строки id длинные.
 */
export function auraOf(seed: string): Aura {
  const готовая = КЭШ.get(seed);
  if (готовая) return готовая;

  const u = хеш(seed || "simp");
  const hue = u % 360;
  // Разброс 26–70°: меньше — градиент читается как один цвет, больше —
  // как две несвязанные краски.
  const spread = 26 + ((u >>> 9) % 44);
  const h2 = (hue + spread) % 360;

  const aura: Aura = {
    hue,
    from: `hsl(${hue} 82% 62%)`,
    to: `hsl(${h2} 78% 52%)`,
    ring: `conic-gradient(from 140deg, hsl(${hue} 85% 62%), hsl(${h2} 80% 54%), hsl(${hue} 85% 62%))`,
    wash: `hsl(${hue} 70% 60% / 0.14)`,
    glow: `0 12px 40px -14px hsl(${hue} 80% 55% / 0.55)`,
  };

  КЭШ.set(seed, aura);
  return aura;
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
