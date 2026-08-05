/**
 * Общий щит от гонок: асинхронный эффект стартовал, компонент размонтировался
 * (или эффект перезапустился на новых зависимостях) раньше, чем промис
 * разрешился — `setState` после этого либо шумит в консоли, либо, что хуже,
 * тихо затирает уже актуальное состояние устаревшим ответом.
 *
 * Даёт стабильную `isMounted()` — читать её нужно сразу перед каждым
 * `setState` внутри `.then`/`await`, а не один раз в начале колбэка.
 */

import { useEffect, useRef } from "react";

export function useIsMounted(): () => boolean {
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  return useRef(() => mounted.current).current;
}
