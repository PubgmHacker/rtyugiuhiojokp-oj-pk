/**
 * Мост к нативным возможностям iOS-обёртки (Capacitor).
 *
 * Все функции безопасны в вебе и в Telegram Mini App: если нативной
 * платформы нет, они тихо ничего не делают. Плагины подгружаются
 * динамически, чтобы не утяжелять веб-бандл.
 */

export function isNative(): boolean {
  return !!(window as any)?.Capacitor?.isNativePlatform?.();
}

export function nativePlatform(): "ios" | "android" | "web" {
  return (window as any)?.Capacitor?.getPlatform?.() ?? "web";
}

/** Тёмный статус-бар поверх нашего тёмного фона. */
async function setupStatusBar(): Promise<void> {
  try {
    const { StatusBar, Style } = await import("@capacitor/status-bar");
    await StatusBar.setStyle({ style: Style.Dark });
    // Вёрстка сама учитывает safe-area, поэтому контент уходит под статус-бар
    await StatusBar.setOverlaysWebView({ overlay: true });
  } catch {
    // Плагин недоступен — не критично
  }
}

/** Убираем сплеш только когда интерфейс готов, без «белой вспышки». */
async function hideSplash(): Promise<void> {
  try {
    const { SplashScreen } = await import("@capacitor/splash-screen");
    await SplashScreen.hide({ fadeOutDuration: 220 });
  } catch {
    /* нет плагина — нечего скрывать */
  }
}

/**
 * Регистрация в APNs. Токен уходит на сервер, чтобы приходили
 * уведомления о мэтчах и сообщениях.
 */
export async function registerPushNotifications(
  onToken: (token: string, platform: string) => void | Promise<void>
): Promise<void> {
  if (!isNative()) return;
  try {
    const { PushNotifications } = await import("@capacitor/push-notifications");

    const status = await PushNotifications.checkPermissions();
    let granted = status.receive === "granted";

    if (!granted) {
      const asked = await PushNotifications.requestPermissions();
      granted = asked.receive === "granted";
    }
    if (!granted) return;

    await PushNotifications.addListener("registration", (t) => {
      onToken(t.value, nativePlatform());
    });
    await PushNotifications.addListener("registrationError", (err) => {
      console.warn("Не удалось зарегистрироваться в APNs:", err);
    });

    await PushNotifications.register();
  } catch (e) {
    console.warn("Пуш-уведомления недоступны:", e);
  }
}

/** Сброс бейджа на иконке — вызываем при открытии списка чатов. */
export async function clearNotificationBadge(): Promise<void> {
  if (!isNative()) return;
  try {
    const { PushNotifications } = await import("@capacitor/push-notifications");
    await PushNotifications.removeAllDeliveredNotifications();
  } catch {
    /* не критично */
  }
}

/**
 * Внешние ссылки в нативном приложении обязаны открываться в системном
 * браузере: ссылка, открытая внутри WebView, ломает навигацию и вызывает
 * замечания при ревью App Store.
 */
export async function openExternal(url: string): Promise<void> {
  if (!isNative()) {
    window.open(url, "_blank", "noopener,noreferrer");
    return;
  }
  try {
    const { Browser } = await import("@capacitor/browser");
    await Browser.open({ url, presentationStyle: "popover" });
  } catch {
    window.open(url, "_blank", "noopener,noreferrer");
  }
}

/** Текущие координаты. null — если пользователь отказал или произошла ошибка. */
export async function getCurrentPosition(): Promise<
  { latitude: number; longitude: number } | null
> {
  try {
    if (isNative()) {
      const { Geolocation } = await import("@capacitor/geolocation");
      const perm = await Geolocation.requestPermissions();
      if (perm.location === "denied") return null;
      const pos = await Geolocation.getCurrentPosition({
        enableHighAccuracy: false,
        timeout: 10_000,
      });
      return { latitude: pos.coords.latitude, longitude: pos.coords.longitude };
    }

    if (!navigator.geolocation) return null;
    return await new Promise((resolve) => {
      navigator.geolocation.getCurrentPosition(
        (p) => resolve({ latitude: p.coords.latitude, longitude: p.coords.longitude }),
        () => resolve(null),
        { timeout: 10_000, maximumAge: 300_000 }
      );
    });
  } catch {
    return null;
  }
}

/**
 * Аппаратная кнопка «назад» и возврат приложения из фона.
 * Возвращает функцию отписки.
 */
export async function setupAppLifecycle(handlers: {
  onResume?: () => void;
  onPause?: () => void;
}): Promise<() => void> {
  if (!isNative()) return () => {};
  try {
    const { App } = await import("@capacitor/app");
    const sub = await App.addListener("appStateChange", ({ isActive }) => {
      if (isActive) handlers.onResume?.();
      else handlers.onPause?.();
    });
    return () => {
      sub.remove();
    };
  } catch {
    return () => {};
  }
}

/** Единая инициализация нативной оболочки при старте приложения. */
export async function initNative(): Promise<void> {
  if (!isNative()) return;
  document.documentElement.classList.add("is-native", `is-${nativePlatform()}`);
  await setupStatusBar();
  await hideSplash();
}
