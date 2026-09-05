import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

/**
 * Контраст текста — не вкусовщина, а число, и до сих пор оно жило только в
 * комментариях к токенам. Здесь оно проверяется: тест читает тот же
 * globals.css, что уходит в сборку, достаёт из него цвета и собирает
 * композит так же, как это делает браузер — сперва пол гасит фон, потом
 * стекло кладёт свой белый film. Если кто-то осветлит подписной токен,
 * опустит пол или поднимет плотность плёнки — суите станет красным здесь, а
 * не в чужих глазах.
 */

const CSS = readFileSync(resolve(__dirname, "../globals.css"), "utf8");

type RGB = [number, number, number];

/** Токены заданы hex'ом; ищем первое объявление — это тёмная схема по умолчанию. */
function hexToken(name: string): RGB {
  const m = CSS.match(new RegExp(`${name}:\\s*#([0-9a-fA-F]{6})`));
  if (!m) throw new Error(`токен ${name} не найден`);
  const h = m[1];
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

/** rgb(255 255 255 / 0.08) → 0.08 */
function filmAlpha(name: string): number {
  const m = CSS.match(new RegExp(`${name}:\\s*rgb\\([^)]*/\\s*([0-9.]+)\\s*\\)`));
  if (!m) throw new Error(`плёнка ${name} не найдена`);
  return Number(m[1]);
}

/** color-mix(in srgb, var(--color-bg) 75%, transparent) → 0.75 */
function floorAlpha(): number {
  const m = CSS.match(/--glass-floor:\s*color-mix\(in srgb,\s*var\(--color-bg\)\s*(\d+)%/);
  if (!m) throw new Error("пол --glass-floor не найден");
  return Number(m[1]) / 100;
}

const lin = (c: number) => {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
};
const luminance = ([r, g, b]: RGB) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
const contrast = (a: RGB, b: RGB) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

const mix = (a: RGB, b: RGB, t: number): RGB =>
  [0, 1, 2].map((i) => a[i] * t + b[i] * (1 - t)) as RGB;

/** Плашка: пол гасит фон, сверху белый film заданной плотности. */
function plate(backdrop: RGB, film: number, withFloor: boolean): RGB {
  const under = withFloor ? mix(BG, backdrop, FLOOR) : backdrop;
  return mix([255, 255, 255], under, film);
}

const BG = hexToken("--color-bg");
const SURFACE_2 = hexToken("--color-surface-2");
const TEXT = hexToken("--color-text");
const SECONDARY = hexToken("--color-text-secondary");
const MUTED = hexToken("--color-text-muted");
const FAINT = hexToken("--color-text-faint");
const FLOOR = floorAlpha();

/**
 * Самая светлая точка живого фона под контентом. Не выдумана: снята с
 * прогона 14 фаз анимации орбов (ядро искры --spark), см. комментарий к
 * --glass-floor. Здесь она — граница худшего случая для плашек.
 */
const ЖИВОЙ_ПИК: RGB = [110, 92, 136];

const AA_МЕЛКИЙ = 4.5;

describe("контраст текста", () => {
  it("все четыре ступени читаются на канве", () => {
    for (const [имя, цвет] of [
      ["text", TEXT],
      ["secondary", SECONDARY],
      ["muted", MUTED],
      ["faint", FAINT],
    ] as const) {
      expect(contrast(цвет, BG), `${имя} на канве`).toBeGreaterThanOrEqual(AA_МЕЛКИЙ);
    }
  });

  it("служебный faint держит AA на surface-2 — им набраны таймстемпы и дисклеймеры", () => {
    expect(contrast(FAINT, SURFACE_2)).toBeGreaterThanOrEqual(AA_МЕЛКИЙ);
  });

  it("подписи на стекле выживают над самым светлым местом живого фона", () => {
    const роли: Array<[string, string]> = [
      ["glass", "--glass-bg"],
      ["glass-soft", "--glass-bg-soft"],
      ["glass-strong", "--glass-bg-strong"],
    ];
    for (const [роль, токен] of роли) {
      const п = plate(ЖИВОЙ_ПИК, filmAlpha(токен), true);
      expect(contrast(MUTED, п), `text-muted на ${роль}`).toBeGreaterThanOrEqual(AA_МЕЛКИЙ);
    }
  });

  it("без пола та же подпись проваливается — пол не украшение", () => {
    const без = plate(ЖИВОЙ_ПИК, filmAlpha("--glass-bg"), false);
    expect(contrast(MUTED, без)).toBeLessThan(AA_МЕЛКИЙ);
  });

  it("пол гасит яркость, но не цвет: над орбом плашка остаётся сиреневой", () => {
    const надОрбом = plate(ЖИВОЙ_ПИК, filmAlpha("--glass-bg"), true);
    const надПустым = plate(BG, filmAlpha("--glass-bg"), true);
    const размах = (c: RGB) => Math.max(...c) - Math.min(...c);
    expect(размах(надОрбом)).toBeGreaterThan(размах(надПустым));
  });

  it("самый бледный токен для мелкой подписи на панели не годится — потому вкладки набраны muted", () => {
    const панель = plate(ЖИВОЙ_ПИК, filmAlpha("--glass-bg-strong"), true);
    expect(contrast(FAINT, панель)).toBeLessThan(contrast(MUTED, панель));
  });
});
