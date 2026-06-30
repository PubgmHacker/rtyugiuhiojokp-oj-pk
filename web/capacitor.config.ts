import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "com.souldawn.dating",
  appName: "Souldawn Dating",
  webDir: "dist",
  bundledWebRuntime: false,
  server: {
    // Для разработки можно указать URL live reload:
    // url: "http://192.168.1.100:5173",
    // cleartext: true,
    androidScheme: "https",
    iosScheme: "https",
  },
  plugins: {
    SplashScreen: {
      launchShowDuration: 1500,
      backgroundColor: "#0a0a1a",
      showSpinner: false,
      androidSplashResourceName: "splash",
      androidScaleType: "CENTER_CROP",
      iosSpinnerStyle: "small",
      iosSpinnerColor: "#ff6b9d",
    },
    PushNotifications: {
      presentationOptions: ["badge", "sound", "alert"],
    },
  },
  ios: {
    contentInset: "always",
    backgroundColor: "#0a0a1a",
    // Apple Sign-In requirement
    scrollEnabled: true,
  },
  android: {
    backgroundColor: "#0a0a1a",
    allowMixedContent: false,
  },
};

export default config;
