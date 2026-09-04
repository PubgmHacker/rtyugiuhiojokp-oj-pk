import { useEffect, useState, useCallback } from "react";
import { useNavigate, Link } from "react-router-dom";
import { motion } from "framer-motion";
import {
  Users, ChevronRight, Mic, Lock, WifiOff,
  Video, Image as ImageIcon, Film,
} from "lucide-react";
import type { DailyLimits, MatchResponse } from "../lib/api";
import { letterAvatarStyle } from "../lib/aura";
import { getMatches, getDailyLimits, ПОТОЛОК_ЧАТОВ } from "../lib/api";
import { useStore } from "../lib/store";
import { haptic } from "../lib/haptics";
import { clearNotificationBadge } from "../lib/native";
import BrandMark from "../components/BrandMark";
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

/**
 * Превью последнего сообщения в строке чата.
 *
 * Медиа обязано отличаться от текста значком: строка «Голосовое сообщение»
 * выглядела ровно так же, как если бы собеседник напечатал эти слова
 * руками, и по списку было не видно, где переписка, а где разговор. Длину
 * записи ставим вместо подписи — как в Telegram: сколько слушать, видно до
 * открытия чата. «Вы:» впереди отвечает на главный вопрос списка — ждут
 * ответа от меня или от него.
 */
const ЗНАЧОК_ВИДА = {
  voice: Mic,
  video_note: Video,
  photo: ImageIcon,
  reel: Film,
} as const;

const ПОДПИСЬ_ВИДА: Record<keyof typeof ЗНАЧОК_ВИДА, string> = {
  voice: "Голосовое сообщение",
  video_note: "Видеосообщение",
  photo: "Фотография",
  reel: "Видео",
};

/** Секунды в 0:07 — как в плеере, а не «7 сек». */
function длинаЗаписи(sec?: number | null): string {
  if (!sec || sec < 1) return "";
  return `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, "0")}`;
}

function ПревьюЧата({ m }: { m: MatchResponse }) {
  const вид = m.last_message_kind ?? null;
  const значок = вид && вид in ЗНАЧОК_ВИДА
    ? ЗНАЧОК_ВИДА[вид as keyof typeof ЗНАЧОК_ВИДА]
    : null;
  const Значок = значок;
  const длина = длинаЗаписи(m.last_message_duration);
  const подпись =
    (вид === "voice" || вид === "video_note") && длина ? длина : m.last_message || "";

  return (
    <p
      className={`flex items-center gap-1 text-[13.5px] ${
        m.unread_count ? "text-text font-medium" : "text-text-muted"
      }`}
    >
      {m.last_message_outgoing && (
        <span className="shrink-0 text-text-faint">Вы:</span>
      )}
      {Значок && (
        <>
          <Значок size={13} aria-hidden="true" className="shrink-0 text-accent" />
          <span className="sr-only">
            {ПОДПИСЬ_ВИДА[вид as keyof typeof ЗНАЧОК_ВИДА]}
          </span>
        </>
      )}
      <span className="truncate">{подпись}</span>
    </p>
  );
}

/** Ряд-вход в соседний способ познакомиться. Один и тот же и в пустом
 *  экране, и под списком чатов: это не украшение, а вторая дверь. */
function Рельса({
  to,
  icon: Icon,
  label,
  hint,
}: {
  to: string;
  icon: typeof Users;
  label: string;
  hint?: string;
}) {
  return (
    <Link
      to={to}
      onClick={() => haptic("light")}
      className="flex items-center gap-3 px-4 py-3 rounded-[var(--radius-tile)]
                 bg-surface-2 border border-hairline active:bg-surface
                 transition-colors"
    >
      <Icon size={18} className="text-accent shrink-0" />
      <span className="flex-1 min-w-0">
        <span className="block text-[14.5px] font-semibold">{label}</span>
        {hint && (
          <span className="block text-[12.5px] text-text-muted">{hint}</span>
        )}
      </span>
      <ChevronRight size={17} className="text-text-faint shrink-0" />
    </Link>
  );
}

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
      // переписки, и цифра с момента входа в приложение успевает соврать.
      // Но только пока список не упёрся в серверный потолок: за ним сумма
      // по видимым чатам меньше настоящей, и бейдж бы тихо занизился —
      // тогда доверяем цифре из /badges, посчитанной по всей базе
      if (свежие.length < ПОТОЛОК_ЧАТОВ) {
        setUnreadMessages(
          свежие.reduce((sum, m) => sum + (m.unread_count ?? 0), 0)
        );
      }
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
    // Пустой экран здесь — не заглушка, а первый шаг. Иконка в кружке
    // посреди пустоты ничего не объясняла и ничего не предлагала, кроме
    // одной кнопки; вместо неё — как открывается чат (три шага, они же
    // единственное правило продукта) и две живые двери, где можно
    // заговорить с кем-то прямо сейчас, не дожидаясь совпадения.
    return (
      <div>
        <ScreenHeader title="Чаты" />
        <div className="px-4 pt-1 pb-10">
          <h2 className="text-[21px] font-bold leading-tight mb-1.5">
            Здесь появятся переписки
          </h2>
          <p className="text-[14.5px] text-text-muted leading-relaxed max-w-[34ch]">
            Чат открывается сам, когда симпатия взаимна. Никто не пишет
            в пустоту — и вам тоже не напишут без вашего лайка.
          </p>

          <ol className="mt-6 mb-7 relative">
            {/* Нить между шагами: она превращает три строки в путь.
                Концы — ровно в центрах первого и последнего кружка
                (py-2.5 = 10px плюс половина кружка 27px), иначе сверху и
                снизу торчали хвостики в пустоту */}
            <span
              aria-hidden="true"
              className="absolute left-[13px] top-[23.5px] bottom-[23.5px] w-px bg-hairline"
            />
            {[
              ["Смотрите анкеты", "Лента подбирает людей рядом и по интересам"],
              ["Ставите лайк", "Он уходит тихо — человек увидит его у себя"],
              ["Совпали — открылся чат", "Голосовые, кружки и стикеры уже внутри"],
            ].map(([заголовок, пояснение], i) => (
              <li key={заголовок} className="relative flex gap-3.5 py-2.5">
                <span
                  className="relative z-[1] w-[27px] h-[27px] rounded-full shrink-0
                             flex items-center justify-center text-[12.5px] font-bold
                             bg-accent/14 text-accent ring-1 ring-accent/20"
                >
                  {i + 1}
                </span>
                <span className="min-w-0 pt-[3px]">
                  <span className="block text-[14.5px] font-semibold leading-snug">
                    {заголовок}
                  </span>
                  <span className="block text-[13px] text-text-muted leading-snug mt-0.5">
                    {пояснение}
                  </span>
                </span>
              </li>
            ))}
          </ol>

          <Button fullWidth onClick={() => navigate("/discover")}>
            Смотреть анкеты
          </Button>

          <p className="text-caption text-text-muted mt-8 mb-2.5">
            Пока никого — говорят здесь
          </p>
          <div className="grid gap-2">
            <Рельса
              to="/rooms"
              icon={Users}
              label="Чаты по интересам"
              hint="Общая комната: написать первым проще, чем в личку"
            />
            <Рельса
              to="/voice"
              icon={Mic}
              label="Голосовая рулетка"
              hint="Минута голосом говорит больше десяти сообщений"
            />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div>
      <ScreenHeader
        title="Чаты"
        /* Считаем то, что человек видит списком, — переписки. «3 совпадения»
           под заголовком «Чаты» пересчитывали и беседы без взаимного лайка,
           и мэтчи из верхней ленты, где переписки ещё нет вовсе */
        subtitle={
          conversations.length
            ? `${conversations.length} ${plural(conversations.length, "переписка", "переписки", "переписок")}`
            : `${matches.length} ${plural(matches.length, "совпадение", "совпадения", "совпадений")}`
        }
      />

      {/* Истории — над списком: они живут сутки, а переписка ждёт. Полоса
          скрывается сама, когда ни у кого ничего нет */}
      <StoriesRail />

      {/* Комнаты и рулетка: в общий чат написать проще, чем первым в личку,
          поэтому обе двери живут рядом со списком переписок */}
      <div className="mx-4 mt-3 grid gap-2">
        <Рельса to="/rooms" icon={Users} label="Чаты по интересам" />
        <Рельса to="/voice" icon={Mic} label="Голосовая рулетка" />
      </div>

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
                      {/* Стрик: серия общения. Стоит вплотную к имени, как
                           в TikTok — это свойство пары, а не отметка времени;
                           у времени он читался как «сообщений в 04:40».
                           Огонёк — наш собственный факел, знак марки: своя
                           серия и должна гореть своим огнём. */}
                      {!!m.streak_days && (
                        <span
                          className="flex items-center gap-[3px] shrink-0
                                     pl-1 pr-1.5 py-[1px] rounded-full
                                     bg-warn/12 text-text-primary text-[11.5px]
                                     font-bold tabular-nums leading-none"
                          aria-label={`Серия общения: ${m.streak_days} дн.`}
                        >
                          {/* Цвет держит только факел: золотая цифра рядом с
                              оранжево-малиновым знаком давала два тёплых тона
                              в одной плашке и читалась грязью */}
                          <BrandMark size={14} solid />
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
                      <ПревьюЧата m={m} />
                    )}
                  </div>
                  {/* Время и счётчик — одной колонкой у правого края. Пока
                      время висело в строке имени, а счётчик стоял отдельным
                      столбцом по центру строки, правый край списка шёл рваной
                      лесенкой: часы на одном отступе, кружок на другом и на
                      другой высоте. В Telegram и VK это один столбик */}
                  {(m.last_message_at || !!m.unread_count) && (
                    <div className="shrink-0 self-start pt-0.5 flex flex-col items-end gap-1">
                      {m.last_message_at && (
                        <span className="text-[11.5px] leading-none text-text-faint tabular-nums">
                          {formatTime(m.last_message_at, язык)}
                        </span>
                      )}
                      {!!m.unread_count && (
                        <span
                          className="min-w-[20px] h-5 px-1.5 rounded-full bg-accent
                                     text-white text-[11px] font-bold
                                     flex items-center justify-center"
                        >
                          {m.unread_count > 99 ? "99+" : m.unread_count}
                        </span>
                      )}
                    </div>
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
