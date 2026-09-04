import { useEffect, useState, useCallback } from "react";
import { useNavigate, Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Users, ChevronRight, Mic, Lock, WifiOff, MessageCircle, Flame } from "lucide-react";
import type { DailyLimits, MatchResponse } from "../lib/api";
import { letterAvatarStyle } from "../lib/aura";
import { getMatches, getDailyLimits } from "../lib/api";
import { useStore } from "../lib/store";
import { haptic } from "../lib/haptics";
import { clearNotificationBadge } from "../lib/native";
import { StoriesRail } from "../components/StoriesRail";
import LimitSheet from "../components/LimitSheet";
import { useЯзык, перевести, форматВремени, форматДаты, type Язык } from "../lib/i18n";
import {
  ScreenHeader,
  EmptyState,
  Skeleton,
  Button,
  IdentityBadge,
} from "../components/ui";

export default function Matches() {
  const navigate = useNavigate();
  const язык = useЯзык();
  const { matches, setMatches, setUnreadMessages } = useStore();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  // Суточный лимит открытых мэтчей. Запрашиваем только если в списке
  // действительно есть закрытые — на подписке этого запроса не будет вовсе
  const [limits, setLimits] = useState<DailyLimits | null>(null);
  const [limitSheet, setLimitSheet] = useState(false);

  const load = useCallback(async () => {
    setError(false);
    try {
      const свежие = await getMatches();
      setMatches(свежие);
      // Бейдж «Чаты» пересчитываем по свежему списку: человек читает
      // переписки, и цифра с момента входа в приложение успевает соврать
      setUnreadMessages(
        свежие.reduce((sum, m) => sum + (m.unread_count ?? 0), 0)
      );
      clearNotificationBadge();
      if (свежие.some((m) => m.locked)) {
        // Нужно только для времени возврата слота в шторке — сам факт
        // блокировки уже пришёл вместе со списком
        getDailyLimits()
          .then(setLimits)
          .catch(() => setLimits(null));
      }
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [setMatches, setUnreadMessages]);

  useEffect(() => {
    load();
  }, [load]);

  const open = useCallback(
    (m: MatchResponse) => {
      // Закрытый мэтч не открываем даже попыткой: сервер всё равно ответит
      // 429, а пустой чат с ошибкой хуже честного объяснения
      if (m.locked) {
        haptic("error");
        setLimitSheet(true);
        return;
      }
      haptic("light");
      navigate(`/chat/${m.id}`);
    },
    [navigate]
  );

  // Пока переписки нет, мэтч живёт в верхней ленте: так виднее, кому
  // ещё стоит написать. Смотрим на время последнего сообщения, а не на его
  // текст: у закрытого мэтча превью вычищено сервером, и по тексту такая
  // беседа уезжала бы в «Новые совпадения» вместе с настоящими новыми
  const fresh = matches.filter((m) => !m.last_message && !m.last_message_at);
  const conversations = matches.filter((m) => m.last_message || m.last_message_at);

  if (loading) {
    return (
      <div>
        <ScreenHeader title="Чаты" />
        <div className="px-4 pt-4">
          <div className="flex gap-3.5 mb-7">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="w-16 h-16 rounded-full shrink-0" />
            ))}
          </div>
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="flex items-center gap-3 mb-4">
              <Skeleton className="w-14 h-14 rounded-full shrink-0" />
              <div className="flex-1">
                <Skeleton className="h-4 w-32 mb-2" />
                <Skeleton className="h-3 w-48" />
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <ScreenHeader title="Чаты" />
        <EmptyState
          icon={WifiOff}
          title="Нет связи"
          description="Не удалось загрузить список. Проверьте подключение к интернету."
          action={<Button onClick={load}>Повторить</Button>}
        />
      </div>
    );
  }

  if (!matches.length) {
    return (
      <div>
        <ScreenHeader title="Чаты" />
        <EmptyState
          icon={MessageCircle}
          title="Пока пусто"
          description="Когда вы понравитесь друг другу, здесь появится чат. Начните с поиска."
          action={
            <Button onClick={() => navigate("/discover")}>Смотреть анкеты</Button>
          }
        />
      </div>
    );
  }

  return (
    <div>
      <ScreenHeader
        title="Чаты"
        subtitle={`${matches.length} ${plural(matches.length, "совпадение", "совпадения", "совпадений")}`}
      />

      {/* Истории — над списком: они живут сутки, а переписка ждёт. Полоса
          скрывается сама, когда ни у кого ничего нет */}
      <StoriesRail />

      {/* Комнаты по интересам: в общий чат написать проще, чем первым в личку,
          поэтому вход в них живёт рядом со списком переписок */}
      <Link
        to="/rooms"
        onClick={() => haptic("light")}
        className="mx-4 mt-3 flex items-center gap-3 px-4 py-3
                   rounded-[var(--radius-tile)] bg-surface-2 border border-hairline"
      >
        <Users size={18} className="text-accent shrink-0" />
        <span className="flex-1 text-[14.5px] font-semibold">
          Чаты по интересам
        </span>
        <ChevronRight size={17} className="text-text-faint shrink-0" />
      </Link>

      {/* Голосом знакомиться проще, чем текстом: голос сразу говорит о
          человеке больше, чем переписка */}
      <Link
        to="/voice"
        onClick={() => haptic("light")}
        className="mx-4 mt-2 flex items-center gap-3 px-4 py-3
                   rounded-[var(--radius-tile)] bg-surface-2 border border-hairline"
      >
        <Mic size={18} className="text-accent shrink-0" />
        <span className="flex-1 text-[14.5px] font-semibold">
          Голосовая рулетка
        </span>
        <ChevronRight size={17} className="text-text-faint shrink-0" />
      </Link>

      {/* ── Новые мэтчи ────────────────────────────────────── */}
      {fresh.length > 0 && (
        <section className="pt-4">
          <h2 className="px-4 text-caption text-text-muted mb-3">
            Новые совпадения
          </h2>
          <div className="flex gap-3.5 px-4 overflow-x-auto no-scrollbar pb-1">
            {fresh.map((m) => (
              <button
                key={m.id}
                onClick={() => open(m)}
                className="flex flex-col items-center gap-1.5 shrink-0 w-[70px]"
              >
                <Avatar
                  src={m.locked ? undefined : m.partner.photos?.[0]}
                  name={m.partner.display_name}
                  seed={m.partner.id}
                  size={64}
                  ring={!m.locked}
                  locked={m.locked}
                />
                <span className="text-[12px] text-text-secondary truncate w-full text-center">
                  {m.locked ? "Закрыт" : m.partner.display_name}
                </span>
              </button>
            ))}
          </div>
        </section>
      )}

      {/* ── Переписки ──────────────────────────────────────── */}
      {conversations.length > 0 && (
        <section className="pt-6">
          <h2 className="px-4 text-caption text-text-muted mb-2">Сообщения</h2>
          <ul>
            {conversations.map((m, i) => (
              <motion.li
                key={m.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: Math.min(i * 0.03, 0.25) }}
              >
                <button
                  onClick={() => open(m)}
                  className="w-full flex items-center gap-3 px-4 py-3
                             active:bg-surface transition-colors text-left"
                >
                  <Avatar
                    src={m.locked ? undefined : m.partner.photos?.[0]}
                    name={m.partner.display_name}
                    seed={m.partner.id}
                    size={56}
                    locked={m.locked}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 mb-0.5">
                      <span
                        className={`font-semibold text-[15px] truncate ${
                          m.locked ? "text-text-muted" : ""
                        }`}
                      >
                        {m.locked ? "Кто-то вам написал" : m.partner.display_name}
                      </span>
                      {/* Наклейка рядом с именем: в списке фото нет, значку
                          лечь некуда. 24px, не меньше: персонажи с деталями
                          (Март 7, Пепе в маске) на 16–20 сливаются в пятно */}
                      {m.partner.sticker && (
                        <img
                          src={m.partner.sticker}
                          alt=""
                          className="w-6 h-6 shrink-0 object-contain"
                        />
                      )}
                      <IdentityBadge profile={m.partner} size={14} />
                      {/* Beседа без взаимного лайка — отличаем визуально: это
                          не мэтч, собеседник может ещё не ответить */}
                      {m.kind === "direct" && !m.locked && (
                        <span
                          className="px-1.5 py-[1px] rounded-full text-[10.5px] font-bold
                                     shrink-0 bg-accent/12 text-accent"
                        >
                          {m.initiator_id === m.partner.id ? "вам написали" : "ваше письмо"}
                        </span>
                      )}
                      {m.last_message_at && (
                        <span className="ml-auto text-[11.5px] text-text-faint shrink-0">
                          {formatTime(m.last_message_at, язык)}
                        </span>
                      )}
                      {/* Стрик: серия общения — эмбиент-индикатор. Рядом с
                           именем, а не на карточке: выбранный эмоджи изменяется
                           от длины серии, и это читается лучше номера. Огонёк —
                           иконка, а не эмодзи сервера: эмодзи в интерфейсе нет. */}
                      {!!m.streak_days && (
                        <span
                          className="flex items-center gap-1 text-[12px]
                                     text-warn font-semibold shrink-0"
                          aria-label={`Серия общения: ${m.streak_days} дн.`}
                        >
                          <Flame size={13} fill="currentColor" aria-hidden="true" />
                          {m.streak_days}
                        </span>
                      )}
                    </div>
                    {m.locked ? (
                      // Превью сервер не отдал — и не должен. Вместо него
                      // прямая причина: так строка объясняет себя сама, без
                      // необходимости открывать шторку
                      <p className="flex items-center gap-1.5 text-[13.5px] text-accent font-medium">
                        <Lock size={12} className="shrink-0" />
                        Лимит мэтчей на сегодня — откройте по подписке
                      </p>
                    ) : (
                      <p
                        className={`text-[13.5px] truncate ${
                          m.unread_count ? "text-text font-medium" : "text-text-muted"
                        }`}
                      >
                        {m.last_message}
                      </p>
                    )}
                  </div>
                  {!!m.unread_count && (
                    <span
                      className="min-w-[20px] h-5 px-1.5 rounded-full bg-accent
                                 text-white text-[11px] font-bold
                                 flex items-center justify-center shrink-0"
                    >
                      {m.unread_count > 99 ? "99+" : m.unread_count}
                    </span>
                  )}
                </button>
              </motion.li>
            ))}
          </ul>
        </section>
      )}

      {/* Один лист на все закрытые строки: объяснение и вход в подписку */}
      <LimitSheet
        kind="matches"
        limits={limits}
        open={limitSheet}
        onClose={() => setLimitSheet(false)}
      />
    </div>
  );
}

/* ── Аватар с градиентной обводкой ──────────────────────────── */

function Avatar({
  src,
  name,
  seed,
  size,
  ring,
  locked,
}: {
  src?: string;
  name?: string;
  /** Семя цвета заглушки — id человека, чтобы плашка была везде одна. */
  seed?: string;
  size: number;
  ring?: boolean;
  /** Мэтч за суточным лимитом: ни фото, ни первой буквы имени. */
  locked?: boolean;
}) {
  if (locked) {
    return (
      <div
        style={{ width: size, height: size }}
        className="rounded-full shrink-0 bg-surface-2 border border-hairline
                   flex items-center justify-center"
      >
        <Lock size={size / 2.8} className="text-text-faint" />
      </div>
    );
  }

  return (
    <div
      style={{ width: size, height: size }}
      className={`rounded-full overflow-hidden shrink-0 ${
        ring ? "avatar-ring" : "bg-surface-2"
      }`}
    >
      {src ? (
        <img
          src={src}
          alt=""
          loading="lazy"
          decoding="async"
          className="w-full h-full object-cover rounded-full"
        />
      ) : (
        <div
          className="w-full h-full rounded-full flex items-center justify-center
                     font-bold"
          style={{ ...letterAvatarStyle(seed), fontSize: size / 2.6 }}
        >
          {name?.[0]?.toUpperCase() ?? "?"}
        </div>
      )}
    </div>
  );
}

/** Сегодня — часы, вчера — «вчера», раньше — дата. */
function formatTime(iso: string, язык: Язык): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";

  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return форматВремени(d, язык);
  }

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString())
    return перевести(язык, "date.yesterdayShort");

  return форматДаты(d, язык);
}

function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}
