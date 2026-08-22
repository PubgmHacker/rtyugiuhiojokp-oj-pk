/**
 * Telegram WebApp SDK helper.
 * Detects if running inside Telegram Mini App and provides initData for auth.
 */

interface TelegramWebApp {
  initData: string;
  initDataUnsafe: {
    user?: {
      id: number;
      first_name: string;
      last_name?: string;
      username?: string;
      photo_url?: string;
    };
  };
  ready: () => void;
  expand: () => void;
  close: () => void;
  themeParams: Record<string, string>;
  colorScheme: "light" | "dark";
  HapticFeedback?: {
    impactOccurred: (style: string) => void;
    notificationOccurred: (type: string) => void;
    selectionChanged: () => void;
  };
  BackButton?: {
    show: () => void;
    hide: () => void;
    onClick: (cb: () => void) => void;
    offClick: (cb: () => void) => void;
  };
  MainButton?: {
    text: string;
    show: () => void;
    hide: () => void;
    setText: (text: string) => void;
    onClick: (cb: () => void) => void;
  };
  showConfirm?: (message: string, callback: (ok: boolean) => void) => void;
  setHeaderColor?: (color: string) => void;
  setBackgroundColor?: (color: string) => void;
  disableVerticalSwipes?: () => void;
  enableClosingConfirmation?: () => void;
  disableClosingConfirmation?: () => void;
  onEvent?: (event: string, cb: () => void) => void;
  offEvent?: (event: string, cb: () => void) => void;
}

export function getTelegramWebApp(): TelegramWebApp | null {
  if (typeof window === "undefined") return null;
  const tg = (window as any).Telegram?.WebApp;
  return tg || null;
}

export function isInTelegram(): boolean {
  return !!getTelegramWebApp()?.initData;
}

export function getInitData(): string {
  return getTelegramWebApp()?.initData || "";
}

/** Светлая или тёмная тема у самого Telegram. Вне Telegram — null. */
export function telegramColorScheme(): "light" | "dark" | null {
  const tg = getTelegramWebApp();
  if (!tg?.initData) return null;
  return tg.colorScheme === "light" ? "light" : "dark";
}

/**
 * Подписка на смену темы в самом Telegram. Возвращает функцию отписки.
 *
 * Нужна ровно для случая, когда схему выбрали не мы: человек переключил
 * Telegram в светлую тему на ходу (или сработал системный автоматический
 * переход в тёмную вечером), а приложение внутри осталось в прежней.
 */
export function onTelegramThemeChange(cb: () => void): () => void {
  const tg = getTelegramWebApp();
  if (!tg?.onEvent) return () => {};
  tg.onEvent("themeChanged", cb);
  return () => tg.offEvent?.("themeChanged", cb);
}

/**
 * Покрасить нативные панели Telegram под текущий фон приложения.
 *
 * Цвет читаем из вычисленного `--color-bg`, а не из константы: схем семь,
 * три из них светлые, и зашитый тёмный цвет давал самый заметный шов
 * продукта — чёрную шапку Telegram над белым холстом «Дня». Зовётся из
 * `applyAppearance`, то есть при каждой смене схемы, и повторно из
 * `initTelegram` после `ready()`: до готовности Mini App цвет мог быть
 * проигнорирован.
 *
 * Мета-тег `theme-color` этого не решает: его читают Safari и WKWebView,
 * а Telegram красит панели только через свой API.
 */
export function syncTelegramChrome(): void {
  const tg = getTelegramWebApp();
  if (!tg) return;
  const bg = getComputedStyle(document.documentElement)
    .getPropertyValue("--color-bg")
    .trim();
  if (!bg) return;
  // Telegram принимает только #rrggbb — токены заданы именно так, но
  // подстраховываемся: невалидный цвет там роняет вызов исключением
  if (!/^#[0-9a-f]{6}$/i.test(bg)) return;
  try {
    tg.setHeaderColor?.(bg);
    tg.setBackgroundColor?.(bg);
  } catch {
    // Старый клиент Telegram без этих методов — не повод ломать экран
  }
}

/**
 * Спрашивать подтверждение при закрытии Mini App.
 *
 * Включаем там, где закрытие стоит человеку работы: незаконченный
 * онбординг, набранный текст. Свайп вниз в Telegram закрывает приложение
 * мгновенно и без предупреждения, а мы этот жест уже отключили в деке
 * (`disableVerticalSwipes`) — подтверждение закрывает остальные пути.
 */
export function setClosingConfirmation(on: boolean): void {
  const tg = getTelegramWebApp();
  if (!tg) return;
  try {
    if (on) tg.enableClosingConfirmation?.();
    else tg.disableClosingConfirmation?.();
  } catch {
    // Метод появился в Bot API 6.2 — на старом клиенте просто нет защиты
  }
}

/**
 * Нативная кнопка «назад» в шапке Telegram.
 *
 * Внутри Telegram это единственная кнопка назад, которую человек ищет
 * глазами: своя стрелка в интерфейсе есть не на каждом экране, а системного
 * жеста «назад» в Mini App нет вовсе — до этого из чата, тарифов и рулетки
 * выходили только через нижнюю навигацию, а из экранов без неё (чат) —
 * никак, кроме закрытия приложения.
 *
 * Возвращает функцию снятия: обработчик обязателен снимать, иначе кнопка
 * копит колбэки от всех посещённых экранов и один тап уводит на несколько
 * шагов назад.
 */
export function showBackButton(onClick: () => void): () => void {
  const tg = getTelegramWebApp();
  const btn = tg?.BackButton;
  if (!tg?.initData || !btn) return () => {};
  btn.onClick(onClick);
  btn.show();
  return () => {
    btn.offClick(onClick);
    btn.hide();
  };
}

export function initTelegram() {
  const tg = getTelegramWebApp();
  if (tg) {
    tg.ready();
    tg.expand();
    // Нативная шапка Telegram по умолчанию красится в тему пользователя —
    // белая полоса над тёмным холстом приложения. Красим под свой фон,
    // каким бы он ни был у выбранной схемы оформления.
    syncTelegramChrome();
    // Вертикальный жест в деке и онбординге не должен сворачивать Mini App:
    // случайное перетаскивание вниз закрывало приложение посреди свайпа.
    tg.disableVerticalSwipes?.();
  }
}

/**
 * Подтверждение действия. В Telegram WebView нативный window.confirm
 * подавлен (молча возвращает false) — «Заблокировать» не срабатывал вовсе.
 * Внутри TMA используем showConfirm, в остальных средах — window.confirm
 * (WKWebView в Capacitor показывает системный диалог корректно).
 */
export function askConfirm(message: string): Promise<boolean> {
  const tg = getTelegramWebApp();
  if (isInTelegram() && tg?.showConfirm) {
    return new Promise((resolve) => {
      try {
        tg.showConfirm!(message, resolve);
      } catch {
        resolve(window.confirm(message));
      }
    });
  }
  return Promise.resolve(window.confirm(message));
}

