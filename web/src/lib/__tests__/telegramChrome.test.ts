/**
 * Нативная обвязка Telegram: покраска панелей, кнопка «назад», следование
 * теме клиента.
 *
 * Почему это тесты, а не «посмотрели глазами». Всё в этом файле невидимо вне
 * Telegram: в браузере и в vitest `window.Telegram` отсутствует, и любая
 * поломка проявляется только на телефоне, у человека, и не в виде ошибки, а
 * в виде «шапка чёрная поверх белого экрана» или «одна кнопка назад уводит
 * на три шага». Такие регрессии не ловятся ни typecheck'ом, ни ревью.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

interface ФейкTelegram {
  initData: string;
  colorScheme: "light" | "dark";
  ready: () => void;
  expand: () => void;
  close: () => void;
  themeParams: Record<string, string>;
  setHeaderColor: (c: string) => void;
  setBackgroundColor: (c: string) => void;
  disableVerticalSwipes: () => void;
  enableClosingConfirmation: () => void;
  disableClosingConfirmation: () => void;
  onEvent: (e: string, cb: () => void) => void;
  offEvent: (e: string, cb: () => void) => void;
  BackButton: {
    show: () => void;
    hide: () => void;
    onClick: (cb: () => void) => void;
    offClick: (cb: () => void) => void;
  };
}

/** Журнал вызовов: проверяем не «не упало», а что именно ушло в SDK. */
const журнал: string[] = [];
/** Подписчики на themeChanged — по ним имитируем смену темы в клиенте. */
let подписчики: Array<() => void> = [];
/** Обработчики, реально висящие на кнопке «назад». */
let обработчики: Array<() => void> = [];

function поставить(схема: "light" | "dark" = "dark"): ФейкTelegram {
  подписчики = [];
  обработчики = [];
  const tg: ФейкTelegram = {
    initData: "query_id=AAA&user=%7B%22id%22%3A1%7D",
    colorScheme: схема,
    ready: () => журнал.push("ready"),
    expand: () => журнал.push("expand"),
    close: () => журнал.push("close"),
    themeParams: { bg_color: "#ffffff" },
    setHeaderColor: (c) => журнал.push(`header:${c}`),
    setBackgroundColor: (c) => журнал.push(`bg:${c}`),
    disableVerticalSwipes: () => журнал.push("noswipe"),
    enableClosingConfirmation: () => журнал.push("confirm:on"),
    disableClosingConfirmation: () => журнал.push("confirm:off"),
    onEvent: (e, cb) => {
      if (e === "themeChanged") подписчики.push(cb);
    },
    offEvent: (e, cb) => {
      if (e === "themeChanged") подписчики = подписчики.filter((x) => x !== cb);
    },
    BackButton: {
      show: () => журнал.push("back:show"),
      hide: () => журнал.push("back:hide"),
      onClick: (cb) => {
        обработчики.push(cb);
        журнал.push("back:on");
      },
      offClick: (cb) => {
        обработчики = обработчики.filter((x) => x !== cb);
        журнал.push("back:off");
      },
    },
  };
  (window as unknown as { Telegram: { WebApp: ФейкTelegram } }).Telegram = {
    WebApp: tg,
  };
  return tg;
}

/** Палитры живут в CSS, которого в jsdom нет — задаём токен явно. */
function фон(цвет: string) {
  document.documentElement.style.setProperty("--color-bg", цвет);
}

beforeEach(() => {
  журнал.length = 0;
  localStorage.clear();
  document.documentElement.removeAttribute("data-appearance");
  document.documentElement.style.removeProperty("--color-bg");
  delete (window as unknown as { Telegram?: unknown }).Telegram;
  vi.resetModules();
});

describe("покраска панелей Telegram", () => {
  it("берёт цвет из текущей схемы, а не из зашитой константы", async () => {
    поставить();
    фон("#f6f7f9"); // светлая схема «День»
    const { syncTelegramChrome } = await import("../telegram");

    syncTelegramChrome();

    expect(журнал).toEqual(["header:#f6f7f9", "bg:#f6f7f9"]);
  });

  it("молчит вне Telegram: в браузере и в iOS-обвязке красить нечего", async () => {
    фон("#0a0b0f");
    const { syncTelegramChrome } = await import("../telegram");

    syncTelegramChrome();

    expect(журнал).toEqual([]);
  });

  it("не отдаёт в SDK невалидный цвет — он там роняет вызов исключением", async () => {
    поставить();
    фон("oklch(0.2 0.05 280)"); // если палитру когда-нибудь переведут на oklch
    const { syncTelegramChrome } = await import("../telegram");

    syncTelegramChrome();

    expect(журнал).toEqual([]);
  });

  it("смена схемы оформления перекрашивает шапку", async () => {
    поставить();
    фон("#0a0b0f");
    const { applyAppearance } = await import("../appearance");

    // Схема ставит свой фон через CSS, которого в jsdom нет: имитируем то,
    // что сделал бы каскад, и проверяем, что новый цвет доехал до SDK
    фон("#f6f7f9");
    applyAppearance("light");

    expect(журнал).toContain("header:#f6f7f9");
  });
});

describe("кнопка «назад»", () => {
  it("снимает свой обработчик — иначе один тап уводит на несколько экранов", async () => {
    поставить();
    const { showBackButton } = await import("../telegram");

    const снять = showBackButton(() => {});
    expect(обработчики).toHaveLength(1);

    снять();

    expect(обработчики).toHaveLength(0);
    expect(журнал).toEqual(["back:on", "back:show", "back:off", "back:hide"]);
  });

  it("вне Telegram возвращает безопасную заглушку", async () => {
    const { showBackButton } = await import("../telegram");

    const снять = showBackButton(() => {});
    снять();

    expect(журнал).toEqual([]);
  });
});

describe("следование теме Telegram", () => {
  it("подставляет светлую схему, пока человек не выбрал свою", async () => {
    поставить("light");
    const { followTelegramTheme, loadAppearance, initAppearance } = await import(
      "../appearance"
    );

    initAppearance(); // как в main.tsx: сохранённой схемы нет
    followTelegramTheme();

    expect(loadAppearance()).toBe("light");
  });

  it("не перебивает явный выбор человека", async () => {
    поставить("light");
    const { applyAppearance, followTelegramTheme, loadAppearance } = await import(
      "../appearance"
    );

    applyAppearance("midnight"); // выбрал сам в шторке оформления
    followTelegramTheme();

    expect(loadAppearance()).toBe("midnight");
  });

  it("догоняет тему, переключённую на ходу", async () => {
    const tg = поставить("dark");
    const { followTelegramTheme, initAppearance, loadAppearance } = await import(
      "../appearance"
    );

    initAppearance();
    const отписаться = followTelegramTheme();
    expect(loadAppearance()).toBe("nebula");

    tg.colorScheme = "light";
    подписчики.forEach((cb) => cb());
    expect(loadAppearance()).toBe("light");

    // Отписка обязательна: подписки копятся так же, как обработчики кнопки
    отписаться();
    expect(подписчики).toHaveLength(0);
  });
});
