/**
 * Кейсы — бонус подписки.
 *
 * У конкурента из кейса выпадают коллекционные персонажи. Здесь награда
 * двойная: полезная — суперлайки и минуты буста, они работают сразу; и
 * коллекционная — наклейки и рамки карточки, которые больше нигде не
 * достаются. Первая держит подписку, вторая — интерес к самому кейсу.
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
import { Button, Card, LoadError, ScreenHeader, Skeleton, Spinner } from "../components/ui";
import StickerCollection from "../components/StickerCollection";
import DecorPicker from "../components/DecorPicker";

export default function Cases() {
  useSectionOpen("cases");
  const [state, setState] = useState<CaseState | null>(null);
  const [busy, setBusy] = useState(false);
  const [дубль, setДубль] = useState(false);
  const [won, setWon] = useState<CaseReward | null>(null);
  const [error, setError] = useState("");
  const [сбой, setСбой] = useState(false);

  const загрузить = useCallback(() => {
    setСбой(false);
    setState(null);
    getCaseState()
      .then(setState)
      // Ошибка первой загрузки раньше писалась в error, который рендерится
      // только внутри загруженного экрана — скелетоны висели вечно
      .catch(() => setСбой(true));
  }, []);

  useEffect(загрузить, [загрузить]);

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
        cur
          ? {
              ...cur,
              left: result.left,
              per_month: result.per_month,
              resets_at: result.resets_at ?? cur.resets_at,
            }
          : cur
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
        {сбой ? (
          <LoadError onRetry={загрузить} />
        ) : (
          <div className="px-4 pt-4 flex flex-col gap-3">
            <Skeleton className="h-40 rounded-[var(--radius-tile)]" />
            <Skeleton className="h-32 rounded-[var(--radius-tile)]" />
          </div>
        )}
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
                       rounded-full bg-accent/15"
          >
            <Gift size={36} className="text-accent" />
          </motion.div>

          <p className="text-[17px] font-extrabold mb-1">
            Попыток: {state.left}
          </p>
          <p className="text-caption text-text-muted mb-4">
            {state.per_month === 0
              ? `Попытки даются с подпиской${state.required_tier_name ? ` ${state.required_tier_name}` : ""}`
              : `${state.per_month} ${plural(state.per_month, "попытка", "попытки", "попыток")} в месяц на вашем уровне` +
                (state.left === 0 && state.resets_at
                  ? ` · обновятся ${когда(state.resets_at)}`
                  : "")}
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

          {state.per_month === 0 ? (
            <Link to="/plans" onClick={() => haptic("light")}>
              <Button size="lg" fullWidth>
                Оформить подписку
              </Button>
            </Link>
          ) : (
            <Button
              size="lg"
              fullWidth
              disabled={busy || state.left === 0}
              onClick={open}
            >
              {busy ? (
                <Spinner size={20} />
              ) : state.left === 0 ? (
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

      {/* Рамка — награда за коллекцию, поэтому строго под ней:
          обратный порядок показывал бы цель до того, как понятно,
          чем её брать */}
      <div className="mt-6">
        <DecorPicker />
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

/** «1 сентября» — дата без года и времени: квота обновляется в начале месяца.
 *
 *  Показываем только когда попытки кончились: до этого дата отвлекает от
 *  кнопки, а после — единственное, что человек хочет знать. */
function когда(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "в начале месяца";
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
}
