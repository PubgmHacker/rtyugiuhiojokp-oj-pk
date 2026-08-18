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

export function initTelegram() {
  const tg = getTelegramWebApp();
  if (tg) {
    tg.ready();
    tg.expand();
    // Нативная шапка Telegram по умолчанию красится в тему пользователя —
    // белая полоса над тёмным холстом приложения. Красим под свой фон.
    tg.setHeaderColor?.("#07070c");
    tg.setBackgroundColor?.("#07070c");
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

