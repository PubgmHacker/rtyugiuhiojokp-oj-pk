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
  }
}

