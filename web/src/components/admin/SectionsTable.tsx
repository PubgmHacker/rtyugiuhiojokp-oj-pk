/**
 * Сводка по разделам: кто вообще ими пользуется.
 *
 * Главная колонка — «людей», а не «открытий»: один энтузиаст, открывший кейсы
 * двести раз, не означает, что кейсы нужны продукту. Разделы с нулём тоже
 * показываем — пустая строка самый честный аргумент за удаление.
 */

import { useEffect, useState } from "react";
import { getSectionStats, type SectionStats } from "../../lib/admin";

/** Человеческие названия. Код раздела — из KNOWN_SECTIONS в API. */
const TITLES: Record<string, string> = {
  reels: "Видео (Reels)",
  rooms: "Чаты по интересам",
  voice: "Голосовая рулетка",
  photo_ratings: "Оценка фото",
  cases: "Кейсы",
  leaderboard: "Топ недели",
  daily: "Карта дня",
};

const PERIODS = [7, 30, 90];

export default function SectionsTable() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<SectionStats | null>(null);
  const [failed, setFailed] = useState(false);
  const [попытка, setПопытка] = useState(0);

  useEffect(() => {
    setData(null);
    setFailed(false);
    getSectionStats(days)
      .then(setData)
      .catch(() => setFailed(true));
  }, [days, попытка]);

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        {PERIODS.map((p) => (
          <button
            key={p}
            onClick={() => setDays(p)}
            aria-pressed={days === p}
            className={`px-3.5 py-1.5 rounded-full text-[13.5px] font-semibold
                        transition-colors ${
                          days === p
                            ? "bg-accent text-white"
                            : "chip text-text-secondary"
                        }`}
          >
            {p} дней
          </button>
        ))}
      </div>

      {/* Кнопки периода живут и при сбое: смена периода — это тоже повтор */}
      {failed ? (
        <div className="py-6 text-center">
          <p className="text-[14px] text-text-muted mb-3">📡 Не удалось загрузить</p>
          <button
            onClick={() => setПопытка((x) => x + 1)}
            className="px-4 py-2 rounded-xl bg-surface-2 border border-hairline
                       text-[13.5px] font-semibold text-text-secondary"
          >
            Повторить
          </button>
        </div>
      ) : !data ? (
        <p className="text-[14px] text-text-muted">Загрузка…</p>
      ) : (
        <>
          <p className="text-caption text-text-muted mb-3">
            Всего пользователей: {data.total_users}. «Людей» — сколько разных
            человек открывало раздел хотя бы раз.
          </p>

          <div className="flex flex-col gap-2">
            {data.sections.map((s) => (
              <div
                key={s.section}
                className="flex items-center gap-3 px-4 py-3 rounded-[var(--radius-tile)]
                           bg-surface-2 border border-hairline"
              >
                <span className="flex-1 min-w-0 text-[14.5px] font-semibold truncate">
                  {TITLES[s.section] ?? s.section}
                </span>

                {/* Полоса охвата: сравнивать разделы глазами по числам
                    неудобно, а по длине — сразу видно */}
                <span className="hidden sm:block w-24 h-1.5 rounded-full bg-surface-3 overflow-hidden">
                  <span
                    className="block h-full rounded-full bg-accent"
                    style={{ width: `${Math.min(100, s.reach_percent)}%` }}
                  />
                </span>

                <span className="w-14 text-right text-[13px] text-text-muted">
                  {s.reach_percent}%
                </span>
                <span className="w-20 text-right text-[14px] font-bold">
                  {s.users} чел.
                </span>
                <span className="w-24 text-right text-[13px] text-text-muted">
                  {s.opens} откр.
                </span>
              </div>
            ))}
          </div>

          <p className="text-[12px] text-text-faint mt-4 leading-snug">
            Раздел, куда за месяц зашло меньше десятой доли людей, стоит убрать
            из «Ещё» или удалить: он не окупает поддержку и модерацию.
          </p>
        </>
      )}
    </div>
  );
}
