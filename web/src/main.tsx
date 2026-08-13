import React from "react";
import ReactDOM from "react-dom/client";
import { Capacitor } from "@capacitor/core";
import App from "./App";
import { initAppearance } from "./lib/appearance";
import "./styles/globals.css";

// До первого кадра: применение после рендера даёт вспышку базовой темы
initAppearance();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// PWA SW — только в браузерном проде. В Capacitor SW ломает локальные ассеты.
if (
  import.meta.env.PROD &&
  "serviceWorker" in navigator &&
  !Capacitor.isNativePlatform()
) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((err) => {
      console.warn("SW registration failed:", err);
    });
  });
} else if ("serviceWorker" in navigator) {
  navigator.serviceWorker.getRegistrations().then((regs) => {
    regs.forEach((r) => r.unregister());
  });
}
