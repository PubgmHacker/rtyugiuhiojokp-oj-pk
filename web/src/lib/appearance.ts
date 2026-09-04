/**
 * Схемы оформления приложения.
 *
 * Палитры живут в CSS (globals.css), здесь — только список, права и
 * применение атрибута. Смена схемы не трогает ни один экран: утилиты
 * компилируются в var(--color-*), а мы переопределяем токены.
 *
 * Порядок применения важен. Схему ставим из localStorage синхронно, до
 * первого кадра, и только потом сверяем с сервером: ждать ответа значило
 * бы показать вспышку чужой темы на старте.
 */

import { СОБЫТИЕ_СХЕМЫ } from "./chatWallpaper";
import { onTelegramThemeChange, syncTelegramChrome, telegramColorScheme } from "./telegram";

export type AppearanceKey =
  | "dawn"
  | "midnight"
  | "graphite"
  | "light"
  | "sepia"
  | "nebula"
  | "goldleaf";

export interface Appearance {
  key: AppearanceKey;
  name: string;
  hint: string;
  /** Точки предпросмотра: фон, поверхность, акцент. */
  swatch: [string, string, string];
  /**
   * Три орба живого фона — как в Plink (V4Theme: accent, second, third).
   * `null` — схема без орбов: светлым цветное пятно читается грязью на
   * экране, а не воздухом, поэтому «День» и «Сепия» остаются ровными.
   */
  orbs: [string, string, string] | null;
  /**
   * Искра — четвёртое, маленькое и светлое пятно контрастного оттенка.
   * Даёт фону глубину: три близких по кругу цвета без неё читаются одним
   * пятном. `undefined` — схема без искры (графит обещает «без цвета»).
   */
  spark?: string;
  /** Платная схема — доступна с Plus. */
  premium?: boolean;
}

export const APPEARANCES: Appearance[] = [
  {
    // Базовая схема продукта. Ключ заперт в базах и localStorage — не
    // переименовывать. Токены базовой схемы живут в @theme без атрибута.
    key: "nebula",
    name: "Туманность",
    hint: "Основная: глубокий фиолет, живой свет",
    swatch: ["#080615", "#1c1540", "#a855f7"],
    // Фиолет, розовый, индиго — соседи по кругу; блик — лавандово-белый:
    // тёплый на этой канве читался пылью, холодный — лунным светом.
    orbs: ["#a855f7", "#ec4899", "#5560ee"],
    spark: "#e6dcff",
  },
  {
    // Ключ исторический и заперт в базах и localStorage — не переименовывать.
    // Витринное имя нейтральное: продукт не тематизируется под название.
    key: "dawn",
    name: "Классика",
    hint: "Тёмная база, малиновый акцент",
    swatch: ["#0a0b0f", "#1c1f28", "#ff2d6f"],
    // Факел марки: малина и оранж, третий — розовая магента (328°). Тёмный
    // край факела #b81648 на канве не виден вовсе; сливового хвоста нет.
    orbs: ["#ff2d6f", "#ff7a1a", "#e8449a"],
    spark: "#ffe4b8",
  },
  {
    key: "midnight",
    name: "Полночь",
    hint: "Глубокая синяя, спокойнее к вечеру",
    swatch: ["#05070f", "#151c38", "#4f7cff"],
    // Как Plink «electric»: акцент, циан, фиолет — соседи по кругу ±35°.
    orbs: ["#4f7cff", "#38c6ff", "#6a4cff"],
    spark: "#d6e4ff",
  },
  {
    key: "graphite",
    name: "Графит",
    hint: "Без цвета совсем — только фотографии",
    swatch: ["#0c0c0d", "#1f1f23", "#d8d8dc"],
    // Орбы без оттенка: дым трёх серых — обещание «без цвета» держится.
    orbs: ["#8e93a3", "#c9ccd6", "#6b7080"],
  },
  {
    key: "light",
    name: "День",
    hint: "Светлая: на улице читается лучше",
    swatch: ["#f6f7f9", "#eff1f5", "#e51f5c"],
    orbs: null,
  },
  {
    key: "sepia",
    name: "Сепия",
    hint: "Тёплая бумага, мягче для глаз",
    swatch: ["#f6f1e7", "#efe6d6", "#b4531f"],
    orbs: null,
  },
  {
    key: "goldleaf",
    name: "Золото",
    hint: "Тёмная с золотом",
    swatch: ["#0b0904", "#1f1a0f", "#d4a72c"],
    // Как Plink «ember»: золото, оранж, кирпичный — третий обязан быть светлым,
    // бронза #8a5a12 на тёмной канве не читалась.
    orbs: ["#d4a72c", "#ff8a3c", "#cf4f2a"],
    spark: "#fff0d6",
    premium: true,
  },
];

export const DEFAULT_APPEARANCE: AppearanceKey = "nebula";

const STORAGE_KEY = "sd_appearance";
//: Схему поставили за человека (по теме Telegram), а не он сам. Флаг нужен,
//: чтобы отличать «выбрал тёмную» от «мы подставили тёмную по умолчанию»:
//: первое надо уважать и не трогать, второе — вести за темой Telegram дальше.
const AUTO_KEY = "sd_appearance_auto";
//: «Живое движение» — плывут ли орбы фона. По умолчанию включено, как в
//: Plink (PlinkAppearancePrefs.livingMotion). Хранится только на устройстве:
//: это про производительность и вкус конкретного телефона, а не про анкету.
const MOTION_KEY = "sd_living_motion";

export function isAppearance(value: unknown): value is AppearanceKey {
  return APPEARANCES.some((a) => a.key === value);
}

export function appearanceByKey(key: string): Appearance {
  return (
    APPEARANCES.find((a) => a.key === key) ??
    APPEARANCES.find((a) => a.key === DEFAULT_APPEARANCE)!
  );
}

/** Схема, выбранная на этом устройстве. */
export function loadAppearance(): AppearanceKey {
  const saved = localStorage.getItem(STORAGE_KEY);
  return isAppearance(saved) ? saved : DEFAULT_APPEARANCE;
}

/**
 * Применить схему к документу.
 *
 * Базовую схему ставим удалением атрибута, а не значением "nebula":
 * иначе селектор :root без атрибута перестал бы работать как база, и
 * добавление схемы требовало бы правки этой функции.
 *
 * `auto` — схему подставили за человека (по теме Telegram). Любой явный
 * выбор — из шторки оформления или приехавший с сервера — снимает признак:
 * дальше следовать за чужой темой значило бы перебивать выбор человека.
 */
export function applyAppearance(
  key: AppearanceKey,
  { auto = false }: { auto?: boolean } = {}
): void {
  const root = document.documentElement;
  if (key === DEFAULT_APPEARANCE) root.removeAttribute("data-appearance");
  else root.setAttribute("data-appearance", key);

  localStorage.setItem(STORAGE_KEY, key);
  if (auto) localStorage.setItem(AUTO_KEY, "1");
  else localStorage.removeItem(AUTO_KEY);

  // Орбы живого фона (components/LivingBackground.tsx) читают переменные
  // с <html>. Палитра живёт здесь, а не в CSS, чтобы предпросмотр в шторке
  // оформления и сам фон красились из одного места.
  const схема = appearanceByKey(key);
  if (схема.orbs) {
    схема.orbs.forEach((цвет, i) => root.style.setProperty(`--orb-${i + 1}`, цвет));
    if (схема.spark) root.style.setProperty("--spark", схема.spark);
    else root.style.removeProperty("--spark");
    root.removeAttribute("data-living");
  } else {
    [1, 2, 3].forEach((i) => root.style.removeProperty(`--orb-${i}`));
    root.style.removeProperty("--spark");
    root.setAttribute("data-living", "off");
  }

  // Telegram Mini App и iOS-обвязка красят свои панели по этому мета-тегу.
  // Без него шапка остаётся тёмной на светлой схеме — самый заметный шов.
  const bg = getComputedStyle(root).getPropertyValue("--color-bg").trim();
  let meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (!meta) {
    meta = document.createElement("meta");
    meta.name = "theme-color";
    document.head.appendChild(meta);
  }
  if (bg) meta.content = bg;

  // Мета-тег читают Safari и WKWebView, но не Telegram — его панели красятся
  // только через собственный API. Вне Telegram вызов ничего не делает.
  syncTelegramChrome();

  // Обои переписки выводятся из --color-bg на JS (lib/chatWallpaper.ts) и
  // сами о смене схемы не узнают: тему Telegram человек может переключить,
  // не выходя из чата. Событие — дешевле наблюдателя за атрибутом.
  window.dispatchEvent(new Event(СОБЫТИЕ_СХЕМЫ));
}

/** Плывут ли орбы фона на этом устройстве. */
export function loadLivingMotion(): boolean {
  return localStorage.getItem(MOTION_KEY) !== "0";
}

/**
 * Включить или заморозить движение орбов.
 *
 * Атрибут, а не класс на слое: фон смонтирован один раз в App и не знает о
 * шторке оформления, а CSS-правило `:root[data-motion="still"]` ставит
 * анимации на паузу там, где они есть. Орбы замирают на месте — без
 * прыжка в исходную позу.
 */
export function applyLivingMotion(on: boolean): void {
  const root = document.documentElement;
  if (on) root.removeAttribute("data-motion");
  else root.setAttribute("data-motion", "still");
  localStorage.setItem(MOTION_KEY, on ? "1" : "0");
}

/** Ставим сохранённую схему до первого кадра — из main.tsx. */
export function initAppearance(): void {
  applyAppearance(loadAppearance(), { auto: !localStorage.getItem(STORAGE_KEY) });
  applyLivingMotion(loadLivingMotion());
}

/**
 * Подтянуть светлую/тёмную тему из Telegram, если человек схему не выбирал.
 *
 * Зачем отдельно от `initAppearance`. SDK Telegram приезжает асинхронно
 * (см. index.html) и на момент первого кадра `colorScheme` может быть ещё
 * неизвестен, а ждать его нельзя — это вспышка чужой темы на старте.
 * Поэтому порядок такой: сначала синхронно ставим сохранённую схему, потом
 * из App, когда SDK точно готов, догоняем тему Telegram.
 *
 * Соответствие простое: светлый Telegram — светлая схема, тёмный — базовая.
 * Полностью повторять `themeParams` мы не станем сознательно: у продукта
 * своя палитра (акцент, поверхности, тени), и подстановка чужих цветов дала
 * бы не «родной вид», а сломанный контраст на каждом втором клиенте.
 *
 * Возвращает функцию отписки: пока схему выбирали не мы, ведём её за
 * Telegram и дальше — человек может переключить тему, не выходя из приложения.
 */
export function followTelegramTheme(): () => void {
  const подстроить = () => {
    if (!localStorage.getItem(AUTO_KEY)) return;
    const схема = telegramColorScheme();
    if (!схема) return;
    const нужная: AppearanceKey = схема === "light" ? "light" : DEFAULT_APPEARANCE;
    if (нужная !== loadAppearance()) applyAppearance(нужная, { auto: true });
  };

  подстроить();
  return onTelegramThemeChange(подстроить);
}
