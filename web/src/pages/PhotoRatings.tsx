/**
 * Оценка фото: показываем чужое фото, человек ставит от 1 до 5.
 *
 * Второй таб — свои оценки: средняя плюс лента «кто и сколько». Оценки
 * видимы (у конкурента — только средняя без имён), а неучастие цельное:
 * «Не участвовать в оценке фото» в приватности прячет и оценщика, и
 * оцениваемого — асимметрия «сам сужу, а меня не судят» не опция.
 *
 * На подбор оценки не влияют. Скрытый рейтинг привлекательности, по которому
 * выдаётся дека, сделал бы сервис, где «некрасивых» никто не видит.
 */

import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Star } from "lucide-react";
import {
  getMyPhotoRating,
  getRatingQueue,
  ratePhoto,
  type MyPhotoRating,
  type PhotoRatingTarget,
} from "../lib/api";
import { haptic } from "../lib/haptics";
import { useSectionOpen } from "../lib/useSectionOpen";
import { EmptyState, LoadError, ScreenHeader, Skeleton } from "../components/ui";

const SCORES = [1, 2, 3, 4, 5];

type Tab = "rate" | "mine";

export default function PhotoRatings() {
  useSectionOpen("photo_ratings");
  const [tab, setTab] = useState<Tab>("rate");

  return (
    <div className="pb-4">
      <ScreenHeader title="Оценка фото" />

      <div className="px-4 pt-1">
        <div className="flex p-1 rounded-full bg-surface-2 border border-hairline">
          {(
            [
              ["rate", "Оценить"],
              ["mine", "Мои оценки"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              onClick={() => {
                haptic("select");
                setTab(value);
              }}
              aria-pressed={tab === value}
              className={`flex-1 py-2 rounded-full text-[14px] font-semibold
                          transition-colors ${
                            tab === value ? "bg-accent text-white" : "text-text-secondary"
                          }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {tab === "rate" ? <RateQueue /> : <MyRating />}
    </div>
  );
}

/* ── Очередь на оценку ──────────────────────────────────────── */

function RateQueue() {
  const [queue, setQueue] = useState<PhotoRatingTarget[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [сбой, setСбой] = useState(false);

  const load = useCallback(async () => {
    try {
      const next = await getRatingQueue();
      setСбой(false);
      setQueue(next);
    } catch {
      // Пустую очередь не подставляем: «Все оценены» при упавшей сети — ложь,
      // а автоподкачка ниже молотила бы запросами каждые 400мс весь офлайн
      setСбой(true);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const rate = useCallback(
    async (score: number) => {
      const current = queue?.[0];
      if (!current || busy) return;
      setBusy(true);
      haptic("light");
      // Карточку убираем сразу: ждать сеть ради следующего фото незачем
      setQueue((cur) => (cur ?? []).slice(1));
      try {
        await ratePhoto(current.user_id, score);
      } catch {
        haptic("error");
      } finally {
        setBusy(false);
      }
    },
    [queue, busy]
  );

  // Кончилась пачка — подтягиваем следующую
  useEffect(() => {
    if (!сбой && queue && queue.length === 0) {
      const timer = window.setTimeout(load, 400);
      return () => window.clearTimeout(timer);
    }
  }, [queue, load, сбой]);

  if (сбой) {
    return (
      <LoadError
        onRetry={() => {
          setQueue(null);
          load();
        }}
      />
    );
  }

  if (!queue) {
    return (
      <div className="px-4 pt-4">
        <Skeleton className="aspect-[3/4] rounded-[var(--radius-card)]" />
      </div>
    );
  }

  const current = queue[0];

  if (!current) {
    return (
      <EmptyState
        emoji="🎯"
        title="Все оценены"
        description="Вы оценили всех, кого нашли. Загляните позже — появятся новые анкеты."
      />
    );
  }

  return (
    <div className="px-4 pt-4">
      <div className="relative aspect-[3/4] rounded-[var(--radius-card)] overflow-hidden bg-surface-2">
        <AnimatePresence mode="popLayout">
          <motion.img
            key={current.user_id}
            src={current.photo}
            alt=""
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 1.04 }}
            transition={{ duration: 0.18 }}
            className="absolute inset-0 w-full h-full object-cover"
          />
        </AnimatePresence>
        <div className="absolute inset-0 bg-scrim pointer-events-none" />
        <p className="absolute bottom-3 left-4 text-[16px] font-bold text-white">
          {current.display_name || "Без имени"}
        </p>
      </div>

      <div className="flex justify-between gap-2 mt-5">
        {SCORES.map((score) => (
          <button
            key={score}
            onClick={() => rate(score)}
            disabled={busy}
            aria-label={`Оценка ${score}`}
            className="flex-1 h-14 rounded-[var(--radius-tile)] bg-surface-2
                       border border-hairline text-[19px] font-extrabold
                       disabled:opacity-50 active:scale-95 transition-transform"
          >
            {score}
          </button>
        ))}
      </div>

      <p className="text-caption text-text-muted text-center mt-3">
        Ваша оценка видна человеку — как и его вам. На подбор не влияет
      </p>
    </div>
  );
}

/* ── Свои оценки ────────────────────────────────────────────── */

function MyRating() {
  const [data, setData] = useState<MyPhotoRating | null>(null);
  const [сбой, setСбой] = useState(false);

  const загрузить = useCallback(() => {
    setСбой(false);
    setData(null);
    getMyPhotoRating()
      .then(setData)
      // Заглушку с пустым фото не подставляем: «Нет фото» при упавшей
      // сети — ложь, человек пойдёт перезаливать фото, которое есть
      .catch(() => setСбой(true));
  }, []);

  useEffect(загрузить, [загрузить]);

  if (сбой) {
    return <LoadError onRetry={загрузить} />;
  }

  if (!data) {
    return (
      <div className="px-4 pt-4">
        <Skeleton className="aspect-[3/4] rounded-[var(--radius-card)]" />
      </div>
    );
  }

  if (!data.photo) {
    return (
      <EmptyState
        emoji="📷"
        title="Нет фото"
        description="Добавьте фото в анкету — тогда его смогут оценить."
      />
    );
  }

  return (
    <div className="px-4 pt-4">
      <div className="relative aspect-[3/4] rounded-[var(--radius-card)] overflow-hidden bg-surface-2">
        <img src={data.photo} alt="" className="w-full h-full object-cover" />
        <div className="absolute inset-0 bg-scrim pointer-events-none" />

        <div
          className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-2
                     px-4 py-2 rounded-full glass-strong"
        >
          <Star size={16} className="text-accent" fill="currentColor" />
          <span className="text-[17px] font-extrabold text-white">
            {data.average ?? "—"}
          </span>
          <span className="text-[13px] text-white/70">
            {data.total} {plural(data.total, "оценка", "оценки", "оценок")}
          </span>
        </div>
      </div>

      <p className="text-caption text-text-muted text-center mt-3">
        {data.total === 0 ? "Ваше фото ещё никто не оценил" : "Свежие оценки — вверху"}
      </p>

      {data.feed.length > 0 && (
        <ul className="mt-4 flex flex-col gap-2" aria-label="Кто и сколько поставил">
          {data.feed.map((item) => (
            <li
              key={item.user_id}
              className="flex items-center gap-3 px-4 py-3 rounded-[var(--radius-tile)]
                         bg-surface border border-hairline"
            >
              {item.photo ? (
                <img
                  src={item.photo}
                  alt=""
                  className="w-11 h-11 rounded-full object-cover shrink-0 bg-surface-2"
                />
              ) : (
                <div
                  aria-hidden
                  className="w-11 h-11 rounded-full shrink-0 bg-surface-2
                             flex items-center justify-center text-[15px] text-text-faint"
                >
                  {(item.display_name || "?").slice(0, 1).toUpperCase()}
                </div>
              )}
              <div className="min-w-0 flex-1">
                <p className="text-[15px] font-semibold text-text truncate">
                  {item.display_name || "Без имени"}
                  {item.age != null && (
                    <span className="font-normal text-text-secondary">, {item.age}</span>
                  )}
                </p>
                {item.city && (
                  <p className="text-[12.5px] text-text-muted truncate">{item.city}</p>
                )}
              </div>
              <span
                aria-label={`Оценка ${item.score} из 5`}
                className="flex items-center gap-1 px-2.5 py-1 rounded-full
                           bg-surface-2 border border-hairline shrink-0"
              >
                <Star size={13} className="text-accent" fill="currentColor" />
                <span className="text-[14px] font-bold text-text">{item.score}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
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
