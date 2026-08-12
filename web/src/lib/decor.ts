/**
 * Рамки карточек — чистый CSS, ни одной картинки.
 *
 * Почему не PNG: рамка обводит карточку целиком, и растр пришлось бы
 * резать под каждую плотность экрана и держать в хранилище. Градиент и
 * тень весят ноль, масштабируются идеально и переживают смену темы.
 *
 * Каждая рамка — два слоя: обводка внутри границы карточки и свечение
 * снаружи. Один слой читается как обычный бордюр и не выглядит наградой.
 */

export interface DecorStyle {
  /** Обводка поверх фото, внутри радиуса карточки. */
  ring: string;
  /** Внешнее свечение — то, что видно на тёмном фоне деки. */
  glow: string;
}

export const DECOR_STYLES: Record<string, DecorStyle> = {
  dawn: {
    ring: "inset 0 0 0 2.5px rgba(255,176,110,.92)",
    glow: "0 0 26px -4px rgba(255,140,80,.55)",
  },
  frost: {
    ring: "inset 0 0 0 2.5px rgba(180,224,255,.95)",
    glow: "0 0 30px -4px rgba(120,200,255,.6)",
  },
  ember: {
    ring: "inset 0 0 0 3px rgba(255,110,90,.95)",
    glow: "0 0 34px -3px rgba(255,80,60,.65)",
  },
  nebula: {
    ring: "inset 0 0 0 3px rgba(196,150,255,.95)",
    glow: "0 0 38px -2px rgba(150,90,255,.7)",
  },
  eclipse: {
    ring: "inset 0 0 0 3px rgba(255,231,150,.98)",
    glow: "0 0 44px -2px rgba(255,205,90,.75)",
  },
};

/** Стиль по коду. Неизвестный код — без рамки, а не сломанная карточка. */
export function decorStyle(code?: string | null): DecorStyle | null {
  if (!code) return null;
  return DECOR_STYLES[code] ?? null;
}

/** Тень для превью в витрине: та же рамка, но на маленьком прямоугольнике. */
export function decorPreviewShadow(code: string): string {
  const s = DECOR_STYLES[code];
  return s ? `${s.ring}, ${s.glow}` : "inset 0 0 0 1px var(--color-border)";
}
