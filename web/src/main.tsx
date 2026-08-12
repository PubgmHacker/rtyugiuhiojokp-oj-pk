import React from "react";
import ReactDOM from "react-dom/client";
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

// Register PWA service worker — только в проде; в dev он отдаёт
// закешированный старый бандл вместо HMR-версии
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((err) => {
      console.warn("SW registration failed:", err);
    });
  });
} else if ("serviceWorker" in navigator) {
  // Убираем ранее установленный SW из dev-браузеров
  navigator.serviceWorker.getRegistrations().then((regs) => {
    regs.forEach((r) => r.unregister());
  });
}
