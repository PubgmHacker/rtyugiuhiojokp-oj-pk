/**
 * Топ по лайкам за неделю.
 *
 * Окно, а не всё время: вечный рейтинг занимают те, кто зарегистрировался
 * раньше, и новичку в него не попасть — стараться незачем.
 *
 * Своё место показываем всегда, даже вне первой десятки: рейтинг, в котором
 * ты себя не находишь, только расстраивает.
 */

import { useEffect, useState } from "react";
import { Crown, Trophy } from "lucide-react";
import { getLeaderboard, type LeaderboardOut } from "../lib/api";
import { Chip, EmptyState, Skeleton } from "./ui";
import { useSectionOpen } from "../lib/useSectionOpen";

export default function Leaderboard() {
  // Считаем открытие таба, а не экрана: у рейтинга своей страницы нет
  useSectionOpen("leaderboard");
  const [period, setPeriod] = useState<"today" | "week">("week");
  const [data, setData] = useState<LeaderboardOut | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setData(null);
    setFailed(false);
    getLeaderboard(period)
      .then(setData)
      .catch(() => setFailed(true));
  }, [period]);

  // Переключатель периода нужен всегда, даже пока данные грузятся или не
  // пришли: иначе переключение работает только когда рейтинг уже непустой,
  // и человек не понимает, что таб вообще есть
  const переключатель = (
    <div className="flex gap-2 mb-3">
      <Chip active={period === "today"} onClick={() => setPeriod("today")}>
        Сегодня
      </Chip>
      <Chip active={period === "week"} onClick={() => setPeriod("week")}>
        Неделя
      </Chip>
    </div>
  );

  if (failed) {
    return (
      <div className="px-4 pt-3">
        {переключатель}
        <EmptyState
          emoji="📊"
          title="Рейтинг недоступен"
          description="Попробуйте зайти позже."
        />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="px-4 pt-3">
        {переключатель}
        <div className="flex flex-col gap-2.5">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-16 rounded-[var(--radius-tile)]" />
          ))}
        </div>
      </div>
    );
  }

  if (!data.entries.length) {
    return (
      <div className="px-4 pt-3">
        {переключатель}
        <EmptyState
          emoji="🏆"
          title="Рейтинг пока пуст"
          description={
            period === "today"
              ? "Лайков сегодня ещё не набралось. Загляните позже."
              : `Лайки за последние ${data.window_days} дней ещё не набрались. Загляните позже.`
          }
        />
      </div>
    );
  }

  return (
    <div className="px-4 pt-3 pb-4">
      {переключатель}
      <p className="text-[13.5px] text-text-muted mb-3">
        {period === "today"
          ? "Больше всего лайков сегодня. Обновляется постоянно."
          : `Больше всего лайков за ${data.window_days} дней. Обновляется постоянно.`}
      </p>

      {/* Своё место сверху: искать себя в списке из двадцати строк неудобно,
          а если места нет вовсе — так и говорим */}
      <div
        className="flex items-center gap-3 mb-4 px-4 py-3 rounded-[var(--radius-tile)]
                   border border-accent/25 bg-accent/8"
      >
        <Trophy size={18} className="text-accent shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-[14.5px] font-semibold">
            {data.my_place_exact && data.my_place
              ? `Вы на ${data.my_place} месте`
              : "Вы пока вне рейтинга"}
          </p>
          <p className="text-caption text-text-muted">
            {data.my_likes > 0
              ? `${data.my_likes} ${plural(data.my_likes, "лайк", "лайка", "лайков")} ${
                  period === "today" ? "сегодня" : "за неделю"
                }`
              : period === "today"
                ? "Лайков сегодня ещё нет"
                : "Лайков за эту неделю ещё нет"}
          </p>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        {data.entries.map((entry) => (
          <div
            key={entry.user_id}
            className={`flex items-center gap-3 px-3 py-2.5 rounded-[var(--radius-tile)]
                        border ${
                          entry.is_me
                            ? "border-accent/40 bg-accent/8"
                            : "border-hairline bg-surface-2"
                        }`}
          >
            <span
              className={`w-7 text-center font-extrabold text-[15px] shrink-0 ${
                entry.place <= 3 ? "text-accent" : "text-text-muted"
              }`}
            >
              {entry.place}
            </span>

            {entry.photo ? (
              <img
                src={entry.photo}
                alt=""
                loading="lazy"
                className="w-11 h-11 rounded-full object-cover shrink-0"
              />
            ) : (
              <span
                className="w-11 h-11 rounded-full flex items-center justify-center
                           text-[15px] font-bold text-white/50 shrink-0"
                style={{ background: "var(--gradient-placeholder)" }}
              >
                {entry.display_name?.[0]?.toUpperCase() ?? "?"}
              </span>
            )}

            <span className="flex-1 min-w-0 text-[15px] font-semibold truncate">
              {entry.display_name || "Без имени"}
              {entry.is_me && (
                <span className="ml-1.5 text-[12px] font-medium text-accent">вы</span>
              )}
            </span>

            <span className="flex items-center gap-1 text-[14px] font-bold shrink-0">
              {entry.place === 1 && <Crown size={14} className="text-accent" />}
              {entry.likes}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}
