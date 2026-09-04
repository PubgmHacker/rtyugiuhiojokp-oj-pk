/**
 * Обои переписки: живой фон вместо плоской заливки.
 *
 * Плоский чёрный или белый фон — главный признак «сделано на выходных».
 * В Telegram под сообщениями лежит мягкий градиент из четырёх цветных пятен
 * плюс необязательный узор-дудл очень низкой интенсивности; во ВКонтакте —
 * то же самое, только пятен меньше. Оба держат фон низкоконтрастным: текст
 * в пузыре обязан остаться главным, поэтому пятна отличаются от базы на
 * несколько единиц светлоты, а не на десятки.
 *
 * Мы не храним четыре цвета в базе — их незачем спрашивать у человека. Пятна
 * ВЫВОДИМ из одного базового цвета поворотом тона: тема пары задаёт `#080615`,
 * а фон сам собой становится туманностью из фиалки, индиго и сливы. У каждой
 * схемы оформления (и у каждой пользовательской темы) обои получаются свои,
 * и ни одной новой колонки для этого не нужно.
 *
 * Узор рисуем тайлом SVG в data-URI, а не картинкой с сервера: сеть в
 * дейтинге дорогая, а узор — украшение, за которое незачем платить запросом.
 * Точки и сетку рисуем градиентами: у них геометрия проще, а градиент даёт
 * ровный пиксель на любом dpr, где тонкая линия в SVG уже мылится.
 */

import { useEffect, useState } from "react";
import type { CSSProperties } from "react";

/** Цвет фона по умолчанию, если схему прочитать не удалось (тесты, SSR). */
const БАЗА = "#080615";

interface Hsl {
  h: number;
  s: number;
  l: number;
}

/** #rrggbb → HSL. Принимает и короткую запись, и пробелы по краям. */
export function вHsl(hex: string): Hsl {
  const s = hex.trim().replace("#", "");
  const п =
    s.length === 3
      ? s
          .split("")
          .map((c) => c + c)
          .join("")
      : s;
  const r = parseInt(п.slice(0, 2), 16) / 255;
  const g = parseInt(п.slice(2, 4), 16) / 255;
  const b = parseInt(п.slice(4, 6), 16) / 255;
  if ([r, g, b].some((v) => Number.isNaN(v))) return { h: 248, s: 56, l: 5 };

  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  if (max === min) return { h: 0, s: 0, l: l * 100 };

  const d = max - min;
  const sat = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h: number;
  if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) * 60;
  else if (max === g) h = ((b - r) / d + 2) * 60;
  else h = ((r - g) / d + 4) * 60;
  return { h, s: sat * 100, l: l * 100 };
}

const тиски = (v: number, min: number, max: number) =>
  Math.min(max, Math.max(min, v));

/** Одно пятно градиента: тон повёрнут, насыщенность и светлота подтянуты. */
function пятно(база: Hsl, dh: number, ds: number, dl: number): string {
  const h = (((база.h + dh) % 360) + 360) % 360;
  const s = тиски(база.s + ds, 6, 82);
  const l = тиски(база.l + dl, 2, 96);
  return `hsl(${h.toFixed(0)} ${s.toFixed(0)}% ${l.toFixed(1)}%)`;
}

/** Тайл узора. Возвращает слой для background-image и его шаг. */
function узор(
  ключ: string | null | undefined,
  светлыйФон: boolean,
): { слой: string; шаг: string } | null {
  if (!ключ || ключ === "none") return null;

  // Дудл на светлом фоне рисуем чернилами, на тёмном — белым. Альфа у
  // тёмных чернил ниже: чёрное по светлому заметнее, чем белое по тёмному.
  const краска = (a: number) =>
    светлыйФон ? `rgba(20,16,32,${(a * 0.72).toFixed(3)})` : `rgba(255,255,255,${a})`;

  const svg = (тайл: number, тело: string) =>
    `url("data:image/svg+xml,${encodeURIComponent(
      `<svg xmlns="http://www.w3.org/2000/svg" width="${тайл}" height="${тайл}" viewBox="0 0 ${тайл} ${тайл}">${тело}</svg>`,
    )}")`;

  const СЕРДЦЕ = "M12 20.7 3.9 12.6a5 5 0 0 1 7.1-7.1l1 1 1-1a5 5 0 1 1 7.1 7.1z";
  const ИСКРА =
    "M12 2.4C12.8 8 16 11.2 21.6 12 16 12.8 12.8 16 12 21.6 11.2 16 8 12.8 2.4 12 8 11.2 11.2 8 12 2.4z";

  const фигуры = (
    путь: string,
    места: [number, number, number, number][],
  ) =>
    места
      .map(
        ([x, y, s, r]) =>
          `<path d="${путь}" transform="translate(${x} ${y}) scale(${s}) rotate(${r} 12 12)"/>`,
      )
      .join("");

  switch (ключ) {
    case "hearts":
      // Сердца трёх калибров с разным наклоном: одинаковые в решётку —
      // это обои из девяностых, а разные читаются как рукописный узор.
      return {
        слой: svg(
          168,
          `<g fill="${краска(0.075)}">${фигуры(СЕРДЦЕ, [
            [10, 14, 0.95, -12],
            [92, 38, 0.62, 14],
            [130, 16, 0.5, -6],
            [46, 82, 1.12, 6],
            [116, 100, 0.8, -20],
            [14, 118, 0.55, 22],
            [76, 136, 0.7, 10],
          ])}</g>`,
        ),
        шаг: "168px 168px",
      };

    case "stars":
      // Четырёхлучевые искры и точки-пылинки между ними: небо, а не
      // рейтинговые звёзды.
      return {
        слой: svg(
          132,
          `<g fill="${краска(0.11)}">${фигуры(ИСКРА, [
            [12, 10, 0.85, 0],
            [78, 30, 0.55, 0],
            [40, 68, 0.62, 0],
            [96, 92, 0.9, 0],
          ])}` +
            `<circle cx="118" cy="20" r="1.1"/><circle cx="64" cy="112" r="1.3"/>` +
            `<circle cx="24" cy="46" r="0.9"/><circle cx="108" cy="60" r="1"/></g>`,
        ),
        шаг: "132px 132px",
      };

    case "waves":
      // Две ленты со сдвигом по фазе. Тайл замыкается по горизонтали:
      // начало и конец на одной высоте с симметричными плечами.
      return {
        слой: svg(
          240,
          `<g fill="none" stroke="${краска(0.09)}" stroke-width="1.6" stroke-linecap="round">` +
            `<path d="M0 52 C 30 22, 90 22, 120 52 S 210 82, 240 52"/>` +
            `<path d="M0 172 C 30 142, 90 142, 120 172 S 210 202, 240 172"/>` +
            `<path d="M-120 112 C -90 82, -30 82, 0 112 S 90 142, 120 112 S 210 82, 240 112"/>` +
            `</g>`,
        ),
        шаг: "240px 240px",
      };

    case "dots":
      return {
        слой: `radial-gradient(${краска(0.1)} 1.1px, transparent 1.2px)`,
        шаг: "22px 22px",
      };

    case "grid":
      return {
        слой:
          `linear-gradient(to right, ${краска(0.07)} 1px, transparent 1px),` +
          `linear-gradient(to bottom, ${краска(0.07)} 1px, transparent 1px)`,
        шаг: "28px 28px, 28px 28px",
      };

    default:
      return null;
  }
}

/** Базовый цвет схемы оформления — из живого CSS, а не из копии палитры. */
export function фонСхемы(): string {
  if (typeof window === "undefined" || !document.documentElement) return БАЗА;
  const v = getComputedStyle(document.documentElement)
    .getPropertyValue("--color-bg")
    .trim();
  return /^#[0-9a-fA-F]{3,8}$/.test(v) ? v : БАЗА;
}

/**
 * Инлайновый стиль для `.chat-surface`.
 *
 * `bg` — цвет темы пары либо null (тогда берём цвет схемы). Всё остальное
 * выводится: три пятна, чернила узора, сам узор.
 */
export function обои(
  bg: string | null | undefined,
  pattern: string | null | undefined,
): CSSProperties {
  const база = bg && /^#[0-9a-fA-F]{6}$/.test(bg) ? bg : фонСхемы();
  const hsl = вHsl(база);
  const светлый = hsl.l > 58;

  // На тёмном фоне пятна светлее базы, на светлом — темнее и чуть плотнее:
  // светлое пятно на белом невидимо, а тёмное читается как тень.
  const шаг = светлый ? -1 : 1;
  const w1 = пятно(hsl, 16, светлый ? 10 : 6, шаг * (светлый ? 4.5 : 9));
  const w2 = пятно(hsl, -26, светлый ? 8 : 3, шаг * (светлый ? 3 : 6));
  const w3 = пятно(hsl, 44, светлый ? 12 : 8, шаг * (светлый ? 5.5 : 4.5));

  const у = узор(pattern, светлый);

  const слои = [
    ...(у ? [у.слой] : []),
    `radial-gradient(128% 78% at 8% -6%, ${w1} 0%, transparent 62%)`,
    `radial-gradient(104% 66% at 96% 14%, ${w2} 0%, transparent 58%)`,
    `radial-gradient(132% 88% at 44% 112%, ${w3} 0%, transparent 66%)`,
  ];
  const шаги = [...(у ? [у.шаг] : []), "auto", "auto", "auto"];

  return {
    backgroundColor: база,
    backgroundImage: слои.join(","),
    backgroundSize: шаги.join(","),
    backgroundRepeat: "repeat",
  } as CSSProperties;
}

/**
 * Имя события смены схемы оформления. `applyAppearance` его шлёт, обои
 * слушают: тему Telegram человек может переключить, не выходя из чата, и
 * обои обязаны переехать вместе с палитрой, а не остаться от прошлой.
 */
export const СОБЫТИЕ_СХЕМЫ = "sd:appearance";

/**
 * Обои переписки как реактивный стиль.
 *
 * Цвет схемы читаем из живого CSS — единственного источника правды о
 * палитре, — и пересчитываем на событие смены схемы.
 */
export function useChatWallpaper(
  bg: string | null | undefined,
  pattern: string | null | undefined,
): CSSProperties {
  const [схема, setСхема] = useState(фонСхемы);

  useEffect(() => {
    const обновить = () => setСхема(фонСхемы());
    обновить();
    window.addEventListener(СОБЫТИЕ_СХЕМЫ, обновить);
    return () => window.removeEventListener(СОБЫТИЕ_СХЕМЫ, обновить);
  }, []);

  const свой = bg && /^#[0-9a-fA-F]{6}$/.test(bg) ? bg : схема;
  return обои(свой, pattern);
}
