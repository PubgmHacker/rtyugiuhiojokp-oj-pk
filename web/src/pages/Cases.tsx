/**
 * Кейсы — бонус подписки.
 *
 * У конкурента из кейса выпадают коллекционные персонажи. Здесь награда
 * полезная: суперлайки и минуты буста, они работают сразу.
 *
 * Шансы показаны рядом с каждой наградой. Скрытые шансы — ровно то, за что
 * гача-механики и не любят, а честные превращают кейс из ловушки в понятный
 * бонус.
 */

import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Gift, Star, Zap } from "lucide-react";
import { Link } from "react-router-dom";
import {
  getCaseState,
  openCase,
  type CaseReward,
  type CaseState,
} from "../lib/api";
import { haptic } from "../lib/haptics";
import { useSectionOpen } from "../lib/useSectionOpen";
import { Button, Card, ScreenHeader, Skeleton, Spinner } from "../components/ui";
import StickerCollection from "../components/StickerCollection";

export default function Cases() {
  useSectionOpen("cases");
  const [state, setState] = useState<CaseState | null>(null);
  const [busy, setBusy] = useState(false);
  const [дубль, setДубль] = useState(false);
  const [won, setWon] = useState<CaseReward | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getCaseState()
      .then(setState)
      .catch(() => setError("Не удалось загрузить кейсы"));
  }, []);

  const open = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    setError("");
    setWon(null);
    try {
      const result = await openCase();
      haptic("success");
      setWon(result.reward);
      setДубль(Boolean(result.duplicate));
      setState((cur) =>
        cur ? { ...cur, left_today: result.left_today, per_day: result.per_day } : cur
      );
    } catch (e: any) {
      haptic("error");
      setError(e?.response?.data?.detail ?? "Не удалось открыть кейс");
    } finally {
      setBusy(false);
    }
  }, [busy]);

  if (!state) {
    return (
      <div>
        <ScreenHeader title="Кейсы" />
        <div className="px-4 pt-4 flex flex-col gap-3">
          <Skeleton className="h-40 rounded-[var(--radius-tile)]" />
          <Skeleton className="h-32 rounded-[var(--radius-tile)]" />
        </div>
      </div>
    );
  }

  return (
    <div className="pb-6">
      <ScreenHeader title="Кейсы" />

      <div className="px-4 pt-3">
        <Card className="p-5 mb-4 text-center">
          <motion.div
            animate={busy ? { rotate: [0, -8, 8, -8, 0] } : { rotate: 0 }}
            transition={{ duration: 0.5, repeat: busy ? Infinity : 0 }}
            className="inline-flex items-center justify-center w-20 h-20 mb-3
                       rounded-full bg-dawn/15"
          >
            <Gift size={36} className="text-accent" />
          </motion.div>

          <p className="text-[17px] font-extrabold mb-1">
            Попыток: {state.left_today}
          </p>
          <p className="text-caption text-text-muted mb-4">
            {state.per_day === 0
              ? "Попытки даются по подписке"
              : `${state.per_day} ${plural(state.per_day, "попытка", "попытки", "попыток")} в сутки на вашем уровне`}
          </p>

          {/* Выигрыш показываем на месте кнопки: отдельная модалка ради одной
              строки только добавляет тап */}
          <AnimatePresence mode="wait">
            {won ? (
              <motion.div
                key="won"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className="mb-3 px-4 py-3 rounded-[var(--radius-tile)]
                           bg-success/12 border border-success/30"
              >
                <div className="flex items-center gap-3">
                  {won.sticker && (
                    <motion.img
                      initial={{ scale: 0.5, rotate: -12 }}
                      animate={{ scale: 1, rotate: 0 }}
                      transition={{ type: "spring", stiffness: 340, damping: 16 }}
                      src={won.sticker.image}
                      alt=""
                      className="w-14 h-14 shrink-0"
                    />
                  )}
                  <div className="min-w-0">
                    <p className="text-[15px] font-bold">Выпало: {won.title}</p>
                    <p className="text-caption text-text-muted">
                      {won.sticker
                        ? дубль
                          ? `Такая уже есть — начислен суперлайк (${won.sticker.rarity_title})`
                          : `Новая в коллекции · ${won.sticker.rarity_title}`
                        : won.code === "boost"
                          ? "Буст уже включён"
                          : "Суперлайки добавлены к вашим"}
                    </p>
                  </div>
                </div>
              </motion.div>
            ) : null}
          </AnimatePresence>

          {state.per_day === 0 ? (
            <Link to="/plans" onClick={() => haptic("light")}>
              <Button size="lg" fullWidth>
                Оформить подписку
              </Button>
            </Link>
          ) : (
            <Button
              size="lg"
              fullWidth
              disabled={busy || state.left_today === 0}
              onClick={open}
            >
              {busy ? (
                <Spinner size={20} />
              ) : state.left_today === 0 ? (
                "Попытки закончились"
              ) : (
                "Открыть кейс"
              )}
            </Button>
          )}

          {error && (
            <p role="alert" className="mt-3 text-[13px] text-danger">
              {error}
            </p>
          )}
        </Card>

        <h2 className="text-caption text-text-muted mb-2.5 px-1">
          Что можно выиграть
        </h2>
        <div className="flex flex-col gap-2">
          {state.rewards.map((reward) => (
            <div
              key={`${reward.code}-${reward.amount}`}
              className="flex items-center gap-3 px-4 py-3 rounded-[var(--radius-tile)]
                         bg-surface-2 border border-hairline"
            >
              {reward.code === "boost" ? (
                <Zap size={17} className="text-warn shrink-0" />
              ) : (
                <Star size={17} className="text-info shrink-0" fill="currentColor" />
              )}
              <span className="flex-1 text-[15px]">{reward.title}</span>
              <span className="text-[13px] font-semibold text-text-muted">
                {reward.chance_percent}%
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Коллекция под витриной шансов: сначала «что можно выиграть», потом
          «что уже собрано» — в этом порядке человек и думает */}
      <StickerCollection />
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
