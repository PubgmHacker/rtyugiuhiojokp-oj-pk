import type { CapacitorConfig } from "@capacitor/cli";

/**
 * Конфигурация нативной обёртки Симп.
 * Цвета синхронизированы с дизайн-системой (web/src/styles/globals.css):
 * фон #0a0b0f, акцент #ff2d6f. Сплэш — первый экран, который видит
 * человек: расхождение с палитрой приложения читается как подмена.
 */
const config: CapacitorConfig = {
  appId: "com.simp.dating",
  appName: "Симп",
  webDir: "dist",

  server: {
    androidScheme: "https",
    // iosScheme намеренно НЕ "https": WKWebView.handlesURLScheme("https") == true,
    // Capacitor сбрасывает схему на capacitor://, а ассеты уходят в сетевой стек
    // с ошибкой -1003 (CannotFindHost) — чёрный экран #0a0b0f без React.
    // Live-reload (только при живом Vite на хосте):
    // url: "http://localhost:5173",
    // cleartext: true,
  },

  plugins: {
    SplashScreen: {
      launchShowDuration: 1200,
      launchAutoHide: true,
      backgroundColor: "#0a0b0f",
      showSpinner: false,
      iosSpinnerStyle: "small",
      spinnerColor: "#ff2d6f",
      splashFullScreen: true,
      splashImmersive: true,
    },
    PushNotifications: {
      presentationOptions: ["badge", "sound", "alert"],
    },
    Keyboard: {
      resize: "native",
      style: "dark",
      resizeOnFullScreen: true,
    },
  },

  ios: {
    // contentInset "never" вместе с safe-area в CSS: раскладку
    // контролирует вёрстка, а не WebView
    contentInset: "never",
    backgroundColor: "#0a0b0f",
    scrollEnabled: true,
    // true без WKAppBoundDomains в Info.plist ломает загрузку capacitor:// ассетов
    limitsNavigationsToAppBoundDomains: false,
    preferredContentMode: "mobile",
  },
};

export default config;
