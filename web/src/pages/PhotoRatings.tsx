/**
 * Оценка фото: показываем чужое фото, человек ставит от 1 до 5.
 *
 * Второй таб — свои оценки. Кто именно поставил, не показываем нигде: оценка
 * анонимна, иначе за тройку прилетит обида конкретному человеку, а честных
 * оценок не станет.
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
import { EmptyState, ScreenHeader, Skeleton } from "../components/ui";

const SCORES = [1, 2, 3, 4, 5];

type Tab = "rate" | "mine";

export default function PhotoRatings() {
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
                            tab === value ? "bg-dawn text-white" : "text-text-secondary"
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

  const load = useCallback(async () => {
    try {
      setQueue(await getRatingQueue());
    } catch {
      setQueue([]);
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
    if (queue && queue.length === 0) {
      const timer = window.setTimeout(load, 400);
      return () => window.clearTimeout(timer);
    }
  }, [queue, load]);

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
        Оценка анонимна и не влияет на подбор
      </p>
    </div>
  );
}

/* ── Свои оценки ────────────────────────────────────────────── */

function MyRating() {
  const [data, setData] = useState<MyPhotoRating | null>(null);

  useEffect(() => {
    getMyPhotoRating()
      .then(setData)
      .catch(() => setData({ photo: "", total: 0, average: null }));
  }, []);

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
        {data.total === 0
          ? "Ваше фото ещё никто не оценил"
          : "Кто поставил оценку, не показываем — так они честнее"}
      </p>
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
