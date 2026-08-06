import { useState, useCallback, useEffect, useRef } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { X, Heart, Star, RotateCcw, SlidersHorizontal, Mail, Zap } from "lucide-react";
import type { DeckProfile, MatchResponse } from "../lib/api";
import {
  likeProfile,
  getDeck,
  resetDeck,
  getSuperlikeQuota,
  recordVisit,
  getBoost,
  activateBoost,
  type BoostState,
} from "../lib/api";
import { useStore } from "../lib/store";
import { haptic } from "../lib/haptics";
import { useIsMounted } from "../hooks/useSafeAsync";
import SwipeCard, { type SwipeDirection } from "./SwipeCard";
import MatchModal from "./MatchModal";
import { Button, IconButton, EmptyState, Skeleton } from "./ui";

interface MatchData {
  partnerName: string;
  partnerPhoto?: string;
  score?: number;
  reason?: string;
  matchId?: string;
}

/** Сколько карточек держим в стеке визуально. */
const VISIBLE_CARDS = 3;
/** Ниже этого порога подгружаем следующую порцию. */
const PREFETCH_AT = 4;

export default function SwipeDeck({ onOpenFilters }: { onOpenFilters?: () => void }) {
  const { deck, setDeck, addDeck, removeDeckProfile, addMatch } = useStore();
  const isMounted = useIsMounted();
  const [matchData, setMatchData] = useState<MatchData | null>(null);
  const [lastSwiped, setLastSwiped] = useState<DeckProfile | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isExhausted, setIsExhausted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Суперлайков на сутки конечное число — кнопка должна это показывать,
  // иначе отказ сервера выглядит как поломка
  const [superlikesLeft, setSuperlikesLeft] = useState<number | null>(null);
  // Лайк с сообщением: пишем до отправки, потому что текст уходит вместе
  // с лайком и увидят его ещё до взаимности
  const [noteFor, setNoteFor] = useState<DeckProfile | null>(null);
  const [boost, setBoost] = useState<BoostState | null>(null);
  const [boostBusy, setBoostBusy] = useState(false);

  const loadingRef = useRef(false);
  // Блокируем повторный свайп, пока текущий не обработан — иначе
  // быстрые тапы отправляют лайк за уже удалённую карточку
  const busyRef = useRef(false);
  // Кому визит уже отправлен в этой сессии: карточка перерисовывается на
  // каждый жест, и без этого один просмотр давал бы десяток запросов
  const visitedRef = useRef<Set<string>>(new Set());

  const loadDeck = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    setError(null);
    try {
      const profiles = await getDeck(10);
      const existing = new Set(useStore.getState().deck.map((p) => p.id));
      const fresh = profiles.filter((p) => !existing.has(p.id));
      if (fresh.length) {
        addDeck(fresh);
        setIsExhausted(false);
      } else {
        // Сервер вернул ноль новых анкет — кандидаты кончились, и неважно,
        // была ли локальная дека пуста на момент запроса. Раньше здесь
        // проверялось `!existing.size`, захваченное до ответа сервера:
        // при свайпах во время запроса дека успевала опустеть, флаг так и
        // не выставлялся, и человек видел «Анкеты закончились» вместо
        // честного «На сегодня всё».
        setIsExhausted(true);
      }
    } catch {
      setError("Не удалось загрузить анкеты");
    } finally {
      loadingRef.current = false;
      setIsLoading(false);
    }
  }, [addDeck]);

  const handleRefresh = useCallback(async () => {
    setIsLoading(true);
    setIsExhausted(false);
    try {
      await resetDeck();
    } catch {
      // Сброс серверного кеша не критичен — всё равно пробуем загрузить
    }
    await loadDeck();
  }, [loadDeck]);

  useEffect(() => {
    if (deck.length < PREFETCH_AT) loadDeck();
  }, [deck.length, loadDeck]);

  useEffect(() => {
    getBoost()
      .then((b) => {
        if (isMounted()) setBoost(b);
      })
      .catch(() => {
        if (isMounted()) setBoost(null); // кнопку тогда не показываем
      });
  }, [isMounted]);

  useEffect(() => {
    getSuperlikeQuota()
      .then((q) => {
        if (isMounted()) setSuperlikesLeft(q.left);
      })
      .catch(() => {
        if (isMounted()) setSuperlikesLeft(null); // счётчик необязателен
      });
  }, [isMounted]);

  // Визит отмечаем для той анкеты, что реально оказалась сверху — не для всей
  // выданной деки: она приходит на десяток вперёд, и записывать её целиком
  // значило бы врать в разделе «Гости»
  useEffect(() => {
    const top = deck[0];
    if (!top || visitedRef.current.has(top.id)) return;
    visitedRef.current.add(top.id);
    recordVisit(top.id);
  }, [deck]);

  const handleBoost = useCallback(async () => {
    if (boostBusy) return;
    setBoostBusy(true);
    haptic("light");
    try {
      setBoost(await activateBoost());
      haptic("success");
    } catch (e: any) {
      haptic("error");
      // 403 — уровень не позволяет, 429 — на сегодня всё. И то и другое
      // человек должен прочитать, а не додумывать
      setError(e?.response?.data?.detail ?? "Не удалось включить буст");
    } finally {
      setBoostBusy(false);
    }
  }, [boostBusy]);

  const handleSwipe = useCallback(
    async (direction: SwipeDirection, profile: DeckProfile, note = "") => {
      if (busyRef.current) return;
      busyRef.current = true;

      const type =
        direction === "left" ? "pass" : direction === "up" ? "superlike" : "like";

      // Оптимистично убираем карточку — интерфейс не должен ждать сеть
      removeDeckProfile(profile.id);
      setLastSwiped(profile);

      try {
        const result = await likeProfile(profile.id, type, note);
        if (type === "superlike") {
          setSuperlikesLeft((n) => (n === null ? n : Math.max(0, n - 1)));
        }
        if (result.matched && result.match) {
          haptic("success");
          setMatchData({
            partnerName: profile.display_name,
            partnerPhoto: profile.photos?.[0],
            score: result.match.match_score ?? undefined,
            reason: result.match.ai_reason ?? undefined,
            matchId: result.match.id,
          });
          addMatch(result.match as MatchResponse);
        }
      } catch (e: any) {
        // Карточку возвращаем всегда: решение пользователя не должно
        // пропадать ни от сбоя сети, ни от исчерпанного лимита
        haptic("error");
        setDeck([profile, ...useStore.getState().deck]);
        setLastSwiped(null);
        if (e?.response?.status === 429) {
          setSuperlikesLeft(0);
          setError(
            e?.response?.data?.detail ?? "Суперлайки на сегодня закончились"
          );
        } else {
          setError("Нет связи — попробуйте ещё раз");
        }
      } finally {
        busyRef.current = false;
      }
    },
    [addMatch, removeDeckProfile, setDeck]
  );

  const handleButton = useCallback(
    (direction: SwipeDirection) => {
      const top = deck[0];
      if (top) handleSwipe(direction, top);
    },
    [deck, handleSwipe]
  );

  const handleRewind = useCallback(() => {
    if (!lastSwiped || busyRef.current) return;
    haptic("light");
    const current = useStore.getState().deck;
    setDeck([lastSwiped, ...current.filter((p) => p.id !== lastSwiped.id)]);
    setLastSwiped(null);
  }, [lastSwiped, setDeck]);

  /* ── Первая загрузка ───────────────────────────────────────── */
  if (isLoading && deck.length === 0) {
    return (
      <div className="flex-1 flex flex-col px-4 pt-2 pb-4 max-w-[440px] mx-auto w-full">
        <Skeleton className="flex-1 rounded-[var(--radius-card)]" />
        <div className="flex items-center justify-center gap-4 mt-5">
          {[44, 60, 44, 60, 44].map((s, i) => (
            <Skeleton key={i} className="rounded-full" style={{ width: s, height: s }} />
          ))}
        </div>
      </div>
    );
  }

  /* ── Анкеты закончились ────────────────────────────────────── */
  if (deck.length === 0) {
    return (
      <EmptyState
        // Разбитое сердце тут читалось как отказ, хотя ничего плохого не
        // произошло: анкеты просто кончились. И везде в продукте «вы» —
        // «ты» осталось только здесь
        emoji="🌅"
        title={isExhausted ? "На сегодня всё" : "Анкеты закончились"}
        description={
          isExhausted
            ? "Вы посмотрели всех, кто подходит. Загляните позже — или расширьте настройки поиска, чтобы увидеть больше людей."
            : "Попробуйте обновить или изменить настройки поиска."
        }
        action={
          <div className="flex flex-col gap-3 w-full max-w-[280px]">
            <Button onClick={handleRefresh} size="lg" fullWidth>
              Обновить
            </Button>
            {onOpenFilters && (
              <Button onClick={onOpenFilters} variant="secondary" size="lg" fullWidth>
                <SlidersHorizontal size={17} />
                Настройки поиска
              </Button>
            )}
          </div>
        }
      />
    );
  }

  const visible = deck.slice(0, VISIBLE_CARDS);

  return (
    <div className="flex-1 flex flex-col px-4 pt-2 pb-3 max-w-[440px] mx-auto w-full min-h-0">
      {/* Стек карточек */}
      <div className="relative flex-1 min-h-0">
        <AnimatePresence initial={false}>
          {visible
            // Верхняя карточка рисуется последней, чтобы лежать поверх стека
            .slice()
            .reverse()
            .map((profile) => {
              const idx = visible.indexOf(profile);
              return (
                <SwipeCard
                  key={profile.id}
                  profile={profile}
                  onSwipe={handleSwipe}
                  isTop={idx === 0}
                  index={idx}
                />
              );
            })}
        </AnimatePresence>

        {/* Действия — вертикальным столбцом поверх карточки: так до них
            дотягивается большой палец, и фото остаётся во всю высоту.
            pointer-events-none на контейнере, чтобы свайп проходил насквозь
            между кнопками */}
        <div
          className="absolute right-3 bottom-28 z-30 flex flex-col items-center gap-3
                     pointer-events-none"
        >
          <div className="pointer-events-auto">
            <IconButton
              label="Вернуть предыдущую анкету"
              onClick={handleRewind}
              disabled={!lastSwiped}
              size={48}
            >
              <RotateCcw size={20} />
            </IconButton>
          </div>

          {/* Буст — молния, как в референсе. Кнопки нет вовсе, если сервер
              не ответил: показывать то, что заведомо не сработает, нельзя */}
          {boost && (
            <div className="relative pointer-events-auto">
              <IconButton
                label={
                  boost.active
                    ? "Буст активен"
                    : boost.left_today
                      ? `Поднять анкету на ${boost.minutes} минут`
                      : boost.per_day
                        ? "Бусты на сегодня закончились"
                        : "Буст доступен в Plus"
                }
                onClick={handleBoost}
                disabled={boostBusy || boost.active}
                size={48}
                tone={boost.active ? "success" : "neutral"}
              >
                <Zap size={20} fill={boost.active ? "currentColor" : "none"} />
              </IconButton>
              {boost.active && (
                <span
                  aria-hidden
                  className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full
                             bg-success ring-2 ring-bg"
                />
              )}
            </div>
          )}

          <div className="relative pointer-events-auto">
            <IconButton
              label={
                superlikesLeft === 0
                  ? "Суперлайки закончились"
                  : superlikesLeft === null
                    ? "Суперлайк"
                    : `Суперлайк, осталось ${superlikesLeft}`
              }
              onClick={() => handleButton("up")}
              disabled={superlikesLeft === 0}
              size={48}
            >
              <Star size={20} fill="currentColor" />
            </IconButton>
            {superlikesLeft !== null && superlikesLeft > 0 && (
              <span
                aria-hidden
                className="absolute -top-1 -right-1 min-w-[16px] h-[16px] px-1
                           rounded-full bg-info text-bg text-[10px] font-bold
                           flex items-center justify-center"
              >
                {superlikesLeft}
              </span>
            )}
          </div>

          {/* Лайк крупнее остальных — главное действие экрана */}
          <div className="pointer-events-auto">
            <IconButton
              label="Лайк"
              onClick={() => handleButton("right")}
              size={64}
              tone="primary"
            >
              <Heart size={28} fill="currentColor" />
            </IconButton>
          </div>

          <div className="pointer-events-auto">
            <IconButton
              label="Лайк с сообщением"
              onClick={() => {
                const top = deck[0];
                if (!top) return;
                haptic("light");
                setNoteFor(top);
              }}
              disabled={!deck.length}
              size={48}
            >
              <Mail size={19} />
            </IconButton>
          </div>

          <div className="pointer-events-auto">
            <IconButton
              label="Пропустить"
              onClick={() => handleButton("left")}
              size={48}
            >
              <X size={22} strokeWidth={2.6} />
            </IconButton>
          </div>
        </div>
      </div>

      {/* Ошибка сети */}
      <AnimatePresence>
        {error && (
          <motion.button
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            onClick={() => setError(null)}
            className="mt-3 mx-auto px-4 py-2 rounded-full bg-danger/15 border border-danger/30
                       text-danger text-[13px] font-medium"
          >
            {error} · закрыть
          </motion.button>
        )}
      </AnimatePresence>

      <LikeNoteSheet
        profile={noteFor}
        onClose={() => setNoteFor(null)}
        onSend={(note) => {
          const target = noteFor;
          setNoteFor(null);
          if (target) handleSwipe("right", target, note);
        }}
      />

      <MatchModal data={matchData} onClose={() => setMatchData(null)} />
    </div>
  );
}

/* ── Шторка ввода сообщения к лайку ─────────────────────────── */

/** Столько же, сколько принимает сервер (LikeRequest.message). */
const MAX_LIKE_NOTE = 200;

function LikeNoteSheet({
  profile,
  onClose,
  onSend,
}: {
  profile: DeckProfile | null;
  onClose: () => void;
  onSend: (note: string) => void;
}) {
  const [note, setNote] = useState("");

  // Текст от предыдущей анкеты не должен уехать новой
  useEffect(() => {
    if (profile) setNote("");
  }, [profile]);

  const trimmed = note.trim();

  return (
    <AnimatePresence>
      {profile && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
          />
          <motion.div
            role="dialog"
            aria-label="Сообщение к лайку"
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", stiffness: 380, damping: 36 }}
            className="fixed bottom-0 left-0 right-0 z-50 bg-bg-elevated
                       rounded-t-[var(--radius-sheet)] border-t border-hairline
                       px-5 pt-3 pb-7 safe-bottom"
          >
            <div className="w-10 h-1 rounded-full bg-surface-3 mx-auto mb-5" />

            <h2 className="text-heading font-bold mb-1.5">
              Написать {profile.display_name}
            </h2>
            <p className="text-caption text-text-muted mb-4">
              Сообщение придёт вместе с лайком — его увидят до взаимности
            </p>

            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value.slice(0, MAX_LIKE_NOTE))}
              rows={3}
              autoFocus
              placeholder="Например: у нас одна любимая группа"
              aria-label="Текст сообщения"
              className="w-full px-3.5 py-3 mb-1.5 rounded-[var(--radius-tile)]
                         bg-surface-2 border border-hairline text-[15px] resize-none
                         placeholder:text-text-muted focus:outline-none
                         focus:border-accent/60"
            />
            <p className="text-[12px] text-text-muted text-right mb-4">
              {note.length} / {MAX_LIKE_NOTE}
            </p>

            <div className="flex gap-2.5">
              <Button variant="secondary" size="lg" onClick={onClose}>
                Отмена
              </Button>
              <Button
                size="lg"
                fullWidth
                disabled={!trimmed}
                onClick={() => onSend(trimmed)}
              >
                Отправить лайк
              </Button>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
