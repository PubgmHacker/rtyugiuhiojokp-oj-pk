import React from "react";
import ReactDOM from "react-dom/client";
import { Capacitor } from "@capacitor/core";
import App from "./App";
import { initAppearance } from "./lib/appearance";
import "./styles/globals.css";

// До первого кадра: применение после рендера даёт вспышку базовой темы
initAppearance();

// Telegram-SDK подгружается из index.html асинхронно и может не приехать
// вовсе (см. комментарий там). Рендер ждёт его исхода, а не сам файл: внутри
// Telegram авторизация читает initData сразу при монтировании, и рендер до
// загрузки SDK показал бы вход по коду человеку, который уже вошёл. Ожидание
// ограничено тремя секундами в index.html, поэтому повиснуть здесь нельзя.
const готовностьTelegram: Promise<unknown> =
  (window as unknown as { __telegramSdkReady?: Promise<boolean> })
    .__telegramSdkReady ?? Promise.resolve(false);

// Отказ ожидания не должен стоить приложения: рендер идёт в любом случае
void готовностьTelegram.catch(() => false).then(() => {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
});

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
  void navigator.serviceWorker
    .getRegistrations()
    .then((regs) => {
      regs.forEach((r) => void r.unregister());
    })
    .catch(() => {
      // В приватном режиме доступ к SW может быть запрещён — это не должно
      // превращаться в unhandled rejection и ломать запуск приложения.
    });
}
