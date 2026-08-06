import type { CapacitorConfig } from "@capacitor/cli";

/**
 * Конфигурация нативной обёртки Souldawn.
 * Цвета синхронизированы с дизайн-системой (web/src/styles/globals.css):
 * фон #100e0e, акцент #e14a35.
 */
const config: CapacitorConfig = {
  appId: "com.souldawn.dating",
  appName: "Souldawn",
  webDir: "dist",

  server: {
    androidScheme: "https",
    iosScheme: "https",
    // Для live-reload при разработке на устройстве раскомментируйте
    // и подставьте адрес машины в локальной сети:
    // url: "http://192.168.1.100:5173",
    // cleartext: true,
  },

  plugins: {
    SplashScreen: {
      launchShowDuration: 1200,
      launchAutoHide: true,
      backgroundColor: "#100e0e",
      showSpinner: false,
      iosSpinnerStyle: "small",
      spinnerColor: "#e14a35",
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
    backgroundColor: "#100e0e",
    scrollEnabled: true,
    limitsNavigationsToAppBoundDomains: true,
    preferredContentMode: "mobile",
  },
};

export default config;
