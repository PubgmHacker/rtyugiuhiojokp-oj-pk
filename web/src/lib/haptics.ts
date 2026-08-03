/**
 * Тактильная отдача и системные жесты.
 *
 * В Telegram Mini App используется Telegram HapticFeedback, на iOS-обёртке
 * Capacitor — нативный плагин, в обычном браузере — Vibration API.
 * Вызов безопасен в любой среде: если ничего не доступно, просто ничего не делает.
 */

export type HapticKind =
  | "light"
  | "medium"
  | "heavy"
  | "soft"
  | "rigid"
  | "success"
  | "error"
  | "warning"
  | "select";

interface TelegramHaptics {
  impactOccurred: (style: string) => void;
  notificationOccurred: (type: string) => void;
  selectionChanged: () => void;
}

function telegramHaptics(): TelegramHaptics | null {
  const tg = (window as any)?.Telegram?.WebApp;
  return tg?.HapticFeedback ?? null;
}

/** Capacitor-плагин доступен только внутри нативной обёртки. */
function capacitorHaptics(): any | null {
  const cap = (window as any)?.Capacitor;
  if (!cap?.isNativePlatform?.()) return null;
  return cap.Plugins?.Haptics ?? null;
}

const VIBRATION_PATTERN: Record<HapticKind, number | number[]> = {
  light: 8,
  soft: 10,
  medium: 16,
  rigid: 20,
  heavy: 28,
  select: 6,
  success: [12, 40, 18],
  error: [24, 50, 24],
  warning: [18, 45, 12],
};

const IMPACT_KINDS = new Set(["light", "medium", "heavy", "soft", "rigid"]);

export function haptic(kind: HapticKind = "light"): void {
  try {
    const native = capacitorHaptics();
    if (native) {
      if (kind === "select") {
        native.selectionChanged?.();
      } else if (IMPACT_KINDS.has(kind)) {
        native.impact?.({ style: kind.toUpperCase() });
      } else {
        native.notification?.({ type: kind.toUpperCase() });
      }
      return;
    }

    const tg = telegramHaptics();
    if (tg) {
      if (kind === "select") tg.selectionChanged();
      else if (IMPACT_KINDS.has(kind)) tg.impactOccurred(kind);
      else tg.notificationOccurred(kind);
      return;
    }

    navigator.vibrate?.(VIBRATION_PATTERN[kind]);
  } catch {
    // Тактильная отдача — украшение, её сбой не должен ломать поток
  }
}
