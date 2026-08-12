import type { CapacitorConfig } from "@capacitor/cli";

/**
 * Конфигурация нативной обёртки Souldawn.
 * Цвета синхронизированы с дизайн-системой (web/src/styles/globals.css):
 * фон #0a0b0f, акцент #ff2d6f. Сплэш — первый экран, который видит
 * человек: расхождение с палитрой приложения читается как подмена.
 */
const config: CapacitorConfig = {
  appId: "com.souldawn.dating",
  appName: "Souldawn",
  webDir: "dist",

  server: {
    androidScheme: "https",
    iosScheme: "https",
    // Live-reload из Vite: в симуляторе «localhost» — это и есть хост-машина,
    // поэтому просто туннелируемся на него.
    url: "http://localhost:5173",
    cleartext: true,
    // Для запуска на реальном устройстве подставьте адрес машины
    // в локальной сети: // url: "http://192.168.1.100:5173",
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
    limitsNavigationsToAppBoundDomains: true,
    preferredContentMode: "mobile",
  },
};

export default config;
