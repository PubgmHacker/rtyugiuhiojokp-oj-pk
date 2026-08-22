/**
 * Нативная кнопка «назад» Telegram, привязанная к экрану.
 *
 * Отдельный хук, а не вызов в каждом экране: кнопка в Telegram одна и
 * глобальная, а её обработчики копятся. Забытый `offClick` в одном экране —
 * и один тап уводит человека на два-три шага назад; поймать это глазами
 * почти невозможно, потому что вне Telegram кнопки нет вовсе.
 *
 * Обработчик держим в ref: экраны пересоздают колбэк на каждом рендере, а
 * перерегистрация кнопки на каждый рендер моргает ею в шапке.
 */

import { useEffect, useRef } from "react";
import { showBackButton } from "./telegram";

/** `null` — кнопку скрыть (например, на первом шаге, откуда назад некуда). */
export function useTelegramBack(onBack: (() => void) | null): void {
  const свежий = useRef(onBack);
  свежий.current = onBack;

  const активна = !!onBack;
  useEffect(() => {
    if (!активна) return;
    return showBackButton(() => свежий.current?.());
  }, [активна]);
}
