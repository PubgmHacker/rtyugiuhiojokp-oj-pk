/**
 * Стена живых экранов для входа.
 *
 * Две наклонённые колонки настоящих скриншотов приложения медленно едут
 * навстречу друг другу. Это не иллюстрация «про знакомства», а само
 * приложение: человек ещё до входа видит ленту, чаты и лайки такими, какие
 * они есть. Список в каждой колонке продублирован — так цикл анимации
 * замыкается без рывка (см. .wall-col в globals.css).
 *
 * Чисто декоративна: aria-hidden, без фокуса, без событий. При
 * prefers-reduced-motion колонки стоят.
 */
import type { CSSProperties } from "react";

const ЭКРАНЫ = ["discover", "matches", "chat", "likes", "reels", "profile"].map(
  (имя) => `/onboarding/${имя}.webp`
);

function Колонка({ items, dir, dur }: { items: string[]; dir: "up" | "down"; dur: string }) {
  // Дубль списка — половина высоты колонки, ровно на неё и сдвигаем
  const список = [...items, ...items];
  return (
    <div className="wall-col" data-dir={dir} style={{ "--wall-dur": dur } as CSSProperties}>
      {список.map((src, i) => (
        <div key={i} className="onb-phone">
          <img src={src} alt="" loading={i < 3 ? "eager" : "lazy"} decoding="async" draggable={false} />
        </div>
      ))}
    </div>
  );
}

export default function ScreenWall({ className = "" }: { className?: string }) {
  return (
    <div className={`wall-mask absolute inset-0 overflow-hidden ${className}`} aria-hidden="true">
      {/* Три узкие колонки, а не две широкие: в кадр попадают целые экраны,
          и стена читается как «много экранов приложения», а не как обрывки
          лиц и пузырей. Скорости разные — движение не выглядит механическим */}
      <div className="wall">
        <Колонка items={[ЭКРАНЫ[0], ЭКРАНЫ[3], ЭКРАНЫ[4]]} dir="down" dur="62s" />
        <Колонка items={[ЭКРАНЫ[1], ЭКРАНЫ[2], ЭКРАНЫ[5]]} dir="up" dur="70s" />
        <Колонка items={[ЭКРАНЫ[2], ЭКРАНЫ[0], ЭКРАНЫ[1]]} dir="down" dur="66s" />
      </div>
      {/* Края растворяем в фоне страницы: стена не должна упираться в шапку
          и кнопки входа резкой линией */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "linear-gradient(to bottom, var(--color-bg) 0%, transparent 26%, transparent 70%, var(--color-bg) 100%)",
        }}
      />
    </div>
  );
}
