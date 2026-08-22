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
  /** Платная схема — доступна с Plus. */
  premium?: boolean;
}

export const APPEARANCES: Appearance[] = [
  {
    // Ключ исторический и заперт в базах и localStorage — не переименовывать.
    // Витринное имя нейтральное: продукт не тематизируется под название.
    key: "dawn",
    name: "Классика",
    hint: "Тёмная база, малиновый акцент",
    swatch: ["#0a0b0f", "#1c1f28", "#ff2d6f"],
  },
  {
    key: "midnight",
    name: "Полночь",
    hint: "Глубокая синяя, спокойнее к вечеру",
    swatch: ["#05070f", "#151c38", "#4f7cff"],
  },
  {
    key: "graphite",
    name: "Графит",
    hint: "Без цвета совсем — только фотографии",
    swatch: ["#0c0c0d", "#1f1f23", "#d8d8dc"],
  },
  {
    key: "light",
    name: "День",
    hint: "Светлая: на улице читается лучше",
    swatch: ["#f6f7f9", "#eff1f5", "#e51f5c"],
  },
  {
    key: "sepia",
    name: "Сепия",
    hint: "Тёплая бумага, мягче для глаз",
    swatch: ["#f6f1e7", "#efe6d6", "#b4531f"],
  },
  {
    key: "nebula",
    name: "Туманность",
    hint: "Фиолетовая, плотная",
    swatch: ["#080615", "#1c1540", "#a855f7"],
    premium: true,
  },
  {
    key: "goldleaf",
    name: "Золото",
    hint: "Тёмная с золотом",
    swatch: ["#0b0904", "#1f1a0f", "#d4a72c"],
    premium: true,
  },
];

export const DEFAULT_APPEARANCE: AppearanceKey = "dawn";

const STORAGE_KEY = "sd_appearance";
//: Схему поставили за человека (по теме Telegram), а не он сам. Флаг нужен,
//: чтобы отличать «выбрал тёмную» от «мы подставили тёмную по умолчанию»:
//: первое надо уважать и не трогать, второе — вести за темой Telegram дальше.
const AUTO_KEY = "sd_appearance_auto";

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
 * Базовую схему ставим удалением атрибута, а не значением "dawn":
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
}

/** Ставим сохранённую схему до первого кадра — из main.tsx. */
export function initAppearance(): void {
  applyAppearance(loadAppearance(), { auto: !localStorage.getItem(STORAGE_KEY) });
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
