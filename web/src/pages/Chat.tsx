import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { askConfirm } from "../lib/telegram";
import { letterAvatarStyle } from "../lib/aura";
import {
  ArrowLeft,
  Send,
  MoreVertical,
  Palette,
  ListChecks,
  Sparkles,
  Flag,
  Ban,
  UserX,
  Check,
  CheckCheck,
  Lock,
} from "lucide-react";
import {
  getMessages,
  getMatches,
  getIcebreakers,
  getChatTheme,
  getDailyLimits,
  reportUser,
  blockUser,
  unmatch,
  type ChatMessage,
  type ChatTheme,
  type DailyLimits,
  type MatchResponse,
} from "../lib/api";
import { ChatWebSocket, type ConnectionStatus } from "../lib/websocket";
import { useStore } from "../lib/store";
import { haptic } from "../lib/haptics";
import { useIsMounted } from "../hooks/useSafeAsync";
import { Button, Skeleton, Spinner, VerifiedBadge } from "../components/ui";
import ReelBubble from "../components/ReelBubble";
import { ChatThemeSheet } from "../components/ChatThemeSheet";
import { HabitsSheet } from "../components/HabitsSheet";
import ProfileSheet from "../components/ProfileSheet";
import { когдаСлот } from "../components/LimitSheet";
import {
  useЯзык,
  перевести,
  форматВремени,
  форматДняРазделителя,
  type Язык,
} from "../lib/i18n";
import { REPORT_REASONS } from "../lib/profileOptions";
import { readableOn } from "../lib/aura";

export default function Chat() {
  const { matchId } = useParams<{ matchId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { token } = useStore();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [match, setMatch] = useState<MatchResponse | null>(null);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [историяНеЗагрузилась, setИсторияНеЗагрузилась] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [partnerTyping, setPartnerTyping] = useState(false);
  const [icebreakers, setIcebreakers] = useState<string[]>([]);
  const [loadingIce, setLoadingIce] = useState(false);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [sendError, setSendError] = useState(false);
  // Сбои жалобы/блокировки/размэтча: раньше catch глотал их молча (одна
  // вибрация), и человек был уверен, что жалоба ушла
  const [actionError, setActionError] = useState("");
  const [theme, setTheme] = useState<ChatTheme | null>(null);
  const [themeOpen, setThemeOpen] = useState(false);
  const [habitsOpen, setHabitsOpen] = useState(false);
  // Профиль собеседника по тапу на шапку: из чата анкету было не открыть
  // вообще (аудит, блок «Продукт»)
  const [profileOpen, setProfileOpen] = useState(false);
  // Мэтч за суточным лимитом бесплатного уровня. Сервер закрывает и историю
  // (429), и сокет (код 4029) — тогда открывать переписку нечем, и вместо
  // пустой ленты с «нет связи» показываем причину
  const [лимитМэтчей, setЛимитМэтчей] = useState(false);
  const [limits, setLimits] = useState<DailyLimits | null>(null);

  const wsRef = useRef<ChatWebSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const typingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastTypingSent = useRef(0);

  const myId = useStore((s) => s.user?.id);
  const язык = useЯзык();
  const isMounted = useIsMounted();
  // Живой matchId на каждый рендер: замыкание эффекта хранит свой matchId
  // навсегда, а этот реф нужен именно для сравнения "а актуален ли ещё тот
  // запрос", когда параметр маршрута уже успел смениться.
  const currentMatchIdRef = useRef(matchId);
  currentMatchIdRef.current = matchId;

  /* ── Загрузка истории и сокет ────────────────────────────── */
  useEffect(() => {
    if (!matchId) return;

    // matchId меняется без размонтирования компонента (переход между
    // чатами по маршруту): если старый запрос ответит позже, чем эффект
    // перезапустится на новом matchId, его результат нельзя применять —
    // иначе он затрёт уже открытую переписку данными чужого матча.
    const requestedMatchId = matchId;
    const stillCurrent = () =>
      isMounted() && requestedMatchId === currentMatchIdRef.current;

    (async () => {
      try {
        const [msgs, matchList] = await Promise.all([
          getMessages(requestedMatchId),
          getMatches(),
        ]);
        if (!stillCurrent()) return;
        // История может прийти позже сокета — мержим без дублей
        setMessages((prev) => {
          const seen = new Set(msgs.map((m) => m.id));
          return [...msgs, ...prev.filter((m) => !seen.has(m.id))];
        });
        setMatch(matchList.find((m) => m.id === requestedMatchId) ?? null);
      } catch (e: any) {
        if (!stillCurrent()) return;
        if (e?.response?.status === 429) {
          // Суточный лимит открытых мэтчей: это не сбой, а закрытая дверь.
          // Подтягиваем время возврата слота, чтобы не обещать «завтра»
          setЛимитМэтчей(true);
          getDailyLimits()
            .then((l) => {
              if (stillCurrent()) setLimits(l);
            })
            .catch(() => {});
        } else {
          // Сбой и «переписки ещё нет» выглядели одинаково: человек видел
          // приглашение написать первым, хотя история просто не загрузилась
          setИсторияНеЗагрузилась(true);
        }
      } finally {
        if (stillCurrent()) setLoading(false);
      }
    })();

    if (!token) return;

    const ws = new ChatWebSocket(matchId, token);
    wsRef.current = ws;

    const offStatus = ws.onStatusChange(setStatus);

    const offMessage = ws.onMessage((data: any) => {
      if (data.type === "message") {
        setMessages((prev) =>
          prev.some((m) => m.id === data.id) ? prev : [...prev, data]
        );
        setPartnerTyping(false);
        if (data.sender_id !== useStore.getState().user?.id) {
          haptic("light");
          ws.sendRaw({ type: "read" });
        }
      } else if (data.type === "typing") {
        // Событие из своей второй вкладки игнорируем
        if (data.user_id === useStore.getState().user?.id) return;
        setPartnerTyping(true);
        if (typingTimer.current) clearTimeout(typingTimer.current);
        typingTimer.current = setTimeout(() => setPartnerTyping(false), 3000);
      } else if (data.type === "read") {
        const now = new Date().toISOString();
        const me = useStore.getState().user?.id;
        setMessages((prev) =>
          prev.map((m) =>
            m.read_at || m.sender_id !== me ? m : { ...m, read_at: now }
          )
        );
      }
    });

    // При открытии чата отмечаем входящие прочитанными
    const offOpen = ws.onOpen(() => ws.sendRaw({ type: "read" }));

    // Сокет тоже упирается в суточный лимит — и закрывается кодом 4029.
    // Без этой ветки экран показывал бы «нет связи»: сообщение о лимите
    // приходит только кодом закрытия, тела у него нет
    const offFatal = ws.onFatalClose((info) => {
      if (!stillCurrent() || info.code !== 4029) return;
      setЛимитМэтчей(true);
      getDailyLimits()
        .then((l) => {
          if (stillCurrent()) setLimits(l);
        })
        .catch(() => {});
    });

    ws.connect();

    return () => {
      offStatus();
      offMessage();
      offOpen();
      offFatal();
      ws.close();
      wsRef.current = null;
      if (typingTimer.current) clearTimeout(typingTimer.current);
    };
  }, [matchId, token]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, partnerTyping]);

  /* ── Отправка ────────────────────────────────────────────── */
  // Тему тянем при входе и при возврате на вкладку: её мог поменять
  // партнёр, а отдельного канала для этого нет — сообщения ходят своим
  // сокетом, и вешать на него оформление значит связать два несвязанных.
  useEffect(() => {
    if (!matchId) return;
    let живо = true;
    const тянуть = () => {
      getChatTheme(matchId)
        .then((t) => живо && setTheme(t))
        .catch(() => {});
    };
    тянуть();
    const onFocus = () => document.visibilityState === "visible" && тянуть();
    document.addEventListener("visibilitychange", onFocus);
    window.addEventListener("focus", onFocus);
    return () => {
      живо = false;
      document.removeEventListener("visibilitychange", onFocus);
      window.removeEventListener("focus", onFocus);
    };
  }, [matchId]);

  // Ответ на историю приходит текстом в состоянии перехода: сама история
  // живёт сутки, а переписка остаётся, поэтому ответ — обычное сообщение.
  useEffect(() => {
    const prefill = (location.state as { prefill?: string } | null)?.prefill;
    if (prefill) {
      setInput(prefill);
      navigate(location.pathname, { replace: true, state: null });
    }
    // Разово при входе: state гасится тут же, и повторный проход стёр бы
    // текст, который человек уже начал править.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const send = useCallback(
    (override?: string) => {
      const text = (override ?? input).trim();
      if (!text || !wsRef.current) return;

      const sent = wsRef.current.send(text);
      if (!sent) {
        // Сокет мог отвалиться — текст не теряем
        if (override) setInput(override);
        setSendError(true);
        haptic("error");
        setTimeout(() => setSendError(false), 3000);
        return;
      }
      setInput("");
      setIcebreakers([]);
      haptic("light");
      if (inputRef.current) inputRef.current.style.height = "auto";
    },
    [input]
  );

  const onInputChange = useCallback((value: string) => {
    setInput(value);

    // Растущее поле: до пяти строк, дальше прокрутка
    const el = inputRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
    }

    const now = Date.now();
    if (now - lastTypingSent.current > 2000 && wsRef.current) {
      wsRef.current.sendRaw({ type: "typing" });
      lastTypingSent.current = now;
    }
  }, []);

  const loadIcebreakers = useCallback(async () => {
    if (!matchId || loadingIce) return;
    setLoadingIce(true);
    haptic("light");
    try {
      setIcebreakers(await getIcebreakers(matchId));
    } catch {
      /* подсказки необязательны */
    } finally {
      setLoadingIce(false);
    }
  }, [matchId, loadingIce]);

  // Причину выбирает человек: раньше любая жалоба уходила как «other», и
  // модератор не понимал, на что смотреть в первую очередь
  const [reportOpen, setReportOpen] = useState(false);

  const sendReport = useCallback(
    async (reason: string) => {
      if (!match) return;
      setReportOpen(false);
      try {
        await reportUser(match.partner.id, reason, "Жалоба из чата");
      } catch (e: any) {
        haptic("error");
        setActionError(
          e?.response?.data?.detail ??
            "Жалоба не отправлена — проверьте связь и попробуйте ещё раз"
        );
        return;
      }
      // Жалоба уже у модератора. Размэтч — вспомогательный шаг: его сбой
      // не должен читаться как «жалоба не ушла», мэтч можно разорвать руками.
      try {
        await unmatch(match.id);
      } catch {
        /* не маскируем принятую жалобу под ошибку */
      }
      haptic("success");
      navigate("/matches", { replace: true });
    },
    [match, navigate]
  );

  const handleBlock = useCallback(async () => {
    if (!match) return;
    const name = match.partner.display_name || "этого пользователя";
    const ok = await askConfirm(
      `Заблокировать ${name}?\n\nВы больше не увидите друг друга и не сможете связаться. Отменить можно в настройках профиля.`
    );
    if (!ok) return;
    try {
      await blockUser(match.partner.id);
      haptic("success");
      navigate("/matches", { replace: true });
    } catch (e: any) {
      haptic("error");
      setActionError(
        e?.response?.data?.detail ??
          "Не удалось заблокировать — попробуйте ещё раз"
      );
    }
  }, [match, navigate]);

  const handleUnmatch = useCallback(async () => {
    if (!match) return;
    if (!(await askConfirm("Разорвать мэтч? Чат исчезнет у обоих."))) return;
    try {
      await unmatch(match.id);
      haptic("medium");
      navigate("/matches", { replace: true });
    } catch (e: any) {
      haptic("error");
      setActionError(
        e?.response?.data?.detail ??
          "Не удалось разорвать мэтч — попробуйте ещё раз"
      );
    }
  }, [match, navigate]);

  /* ── Группировка сообщений ───────────────────────────────── */
  const groups = useMemo(() => groupMessages(messages, myId, язык), [messages, myId, язык]);

  const partnerName = match?.partner.display_name || "Чат";
  const partnerPhoto = match?.partner.photos?.[0];

  /* ── Мэтч закрыт суточным лимитом ────────────────────────── */
  // Отдельным экраном, а не шторкой поверх чата: под шторкой всё равно
  // пусто — ни истории, ни сокета сервер не даст, — и закрыв её человек
  // остался бы на мёртвой странице. Здесь единственный выход осмысленный:
  // подписка или назад к списку
  if (лимитМэтчей) {
    return (
      <div className="flex flex-col h-screen-safe">
        <header className="chrome safe-top border-b border-hairline/70 shrink-0">
          <div className="flex items-center gap-2.5 px-3 pb-2.5 min-h-[52px]">
            <button
              aria-label="Назад"
              onClick={() => navigate(-1)}
              className="tap-target flex items-center justify-center text-text-secondary"
            >
              <ArrowLeft size={22} />
            </button>
            <span className="font-semibold text-[15px]">Мэтч закрыт</span>
          </div>
        </header>

        <div className="flex-1 flex flex-col items-center justify-center px-8 text-center">
          <span
            className="w-16 h-16 rounded-full bg-accent/12 flex items-center
                       justify-center mb-5"
          >
            <Lock size={26} className="text-accent" />
          </span>
          <h2 className="text-heading font-bold mb-2">Лимит мэтчей на сегодня</h2>
          <p className="text-[14px] leading-snug text-text-secondary mb-1.5">
            На бесплатном уровне открыто{" "}
            {limits && limits.matches_total > 0 ? limits.matches_total : 3} мэтча в
            сутки. Уже открытые переписки остаются доступны.
          </p>
          {limits?.matches_reset_at && (
            <p className="text-caption text-text-muted mb-6">
              Следующий слот вернётся {когдаСлот(limits.matches_reset_at, язык)}.
            </p>
          )}
          {!limits?.matches_reset_at && <div className="mb-6" />}

          <div className="flex flex-col gap-2.5 w-full max-w-[280px]">
            <Button
              size="lg"
              fullWidth
              onClick={() => {
                haptic("light");
                navigate("/plans");
              }}
            >
              Открыть без лимитов
            </Button>
            <Button
              variant="secondary"
              size="lg"
              fullWidth
              onClick={() => navigate("/matches")}
            >
              К списку чатов
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen-safe">
      {/* ── Заголовок ───────────────────────────────────────── */}
      <header className="chrome safe-top border-b border-hairline/70 shrink-0 z-20">
        <div className="flex items-center gap-2.5 px-3 pb-2.5 min-h-[52px]">
          <button
            aria-label="Назад"
            onClick={() => navigate(-1)}
            className="tap-target flex items-center justify-center text-text-secondary"
          >
            <ArrowLeft size={22} />
          </button>

          {/* Аватар и имя открывают полный профиль собеседника. Две соседние
              кнопки, а не одна обёртка: внутри блока живёт ссылка канала,
              и интерактив внутри интерактива — ломаный HTML */}
          <button
            aria-label={`Профиль ${partnerName}`}
            disabled={!match}
            onClick={() => {
              haptic("light");
              setProfileOpen(true);
            }}
            className="w-9 h-9 rounded-full overflow-hidden bg-surface-2 shrink-0"
          >
            {partnerPhoto ? (
              <img src={partnerPhoto} alt="" className="w-full h-full object-cover" />
            ) : (
              <span
                className="w-full h-full flex items-center justify-center text-[14px] font-bold"
                style={letterAvatarStyle(match?.partner.id)}
              >
                {partnerName[0]?.toUpperCase()}
              </span>
            )}
          </button>

          <div className="flex-1 min-w-0">
            <button
              disabled={!match}
              onClick={() => {
                haptic("light");
                setProfileOpen(true);
              }}
              className="flex items-center gap-1.5 min-w-0 max-w-full text-left"
            >
              <span className="font-semibold text-[15px] truncate">{partnerName}</span>
              {match?.partner.is_verified && <VerifiedBadge size={14} />}
            </button>
            {/* Канал показывает сервер только если у собеседника открыта эта
                фича по тарифу — здесь просто собираем ссылку из username */}
            {match?.partner.tg_channel ? (
              <a
                href={`https://t.me/${match.partner.tg_channel}`}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="text-[11.5px] text-accent truncate block hover:underline"
              >
                @{match.partner.tg_channel}
              </a>
            ) : (
            <p className="text-[11.5px] text-text-muted truncate">
              {partnerTyping
                ? "печатает…"
                : status === "open"
                  ? "в сети"
                  : status === "connecting"
                    ? "подключение…"
                    : "нет связи"}
            </p>
            )}
          </div>


          <button
            aria-label="Задачи на день"
            onClick={() => {
              haptic("light");
              setHabitsOpen(true);
            }}
            className="tap-target flex items-center justify-center text-text-secondary"
          >
            <ListChecks size={20} />
          </button>

          <button
            aria-label="Тема переписки"
            onClick={() => {
              haptic("light");
              setThemeOpen(true);
            }}
            className="tap-target flex items-center justify-center text-text-secondary"
          >
            <Palette size={20} />
          </button>

          <div className="relative">
            <button
              aria-label="Действия"
              onClick={() => setMenuOpen((v) => !v)}
              className="tap-target flex items-center justify-center text-text-secondary"
            >
              <MoreVertical size={20} />
            </button>

            <AnimatePresence>
              {menuOpen && (
                <>
                  <div className="fixed inset-0 z-30" onClick={() => setMenuOpen(false)} />
                  <motion.div
                    initial={{ opacity: 0, scale: 0.94, y: -6 }}
                    animate={{ opacity: 1, scale: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.96 }}
                    transition={{ type: "spring", stiffness: 420, damping: 30 }}
                    className="absolute right-0 top-11 z-40 w-56 rounded-[var(--radius-tile)]
                               bg-bg-elevated border border-hairline float-shadow overflow-hidden"
                  >
                    <button
                      onClick={() => {
                        setMenuOpen(false);
                        setReportOpen(true);
                      }}
                      className="w-full flex items-center gap-2.5 px-4 py-3 text-left
                                 text-[14.5px] active:bg-surface transition-colors"
                    >
                      <Flag size={16} className="text-warn" />
                      Пожаловаться
                    </button>
                    <button
                      onClick={() => {
                        setMenuOpen(false);
                        handleBlock();
                      }}
                      className="w-full flex items-center gap-2.5 px-4 py-3 text-left
                                 text-[14.5px] border-t border-hairline
                                 active:bg-surface transition-colors"
                    >
                      <Ban size={16} className="text-danger" />
                      Заблокировать
                    </button>
                    <button
                      onClick={() => {
                        setMenuOpen(false);
                        handleUnmatch();
                      }}
                      className="w-full flex items-center gap-2.5 px-4 py-3 text-left
                                 text-[14.5px] text-danger border-t border-hairline
                                 active:bg-surface transition-colors"
                    >
                      <UserX size={16} />
                      Разорвать мэтч
                    </button>
                  </motion.div>
                </>
              )}
            </AnimatePresence>
          </div>
        </div>

        {status !== "open" && !loading && (
          <div className="px-4 pb-2">
            <p role="status" aria-live="polite" className="text-[12px] text-warn text-center">
              {status === "connecting" ? "Переподключение…" : "Нет связи с чатом"}
            </p>
          </div>
        )}
      </header>

      {/* ── Лента сообщений ─────────────────────────────────── */}
      <div
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        aria-label="Переписка"
        className="chat-surface flex-1 min-h-0 overflow-y-auto overscroll-contain
                   no-scrollbar px-3 py-3"
        data-pattern={theme?.pattern_key || "none"}
        style={{
          ["--chat-bg" as any]: theme?.background_color || undefined,
          ["--chat-ink" as any]: theme?.background_color
            ? readableOn(theme.background_color)
            : undefined,
          ["--chat-accent" as any]: theme?.bubble_mine_color || undefined,
        }}
      >
        {loading ? (
          <div className="flex flex-col gap-3">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton
                key={i}
                className={`h-11 ${i % 2 ? "w-2/3 ml-auto" : "w-1/2"} rounded-[18px]`}
              />
            ))}
          </div>
        ) : messages.length === 0 && историяНеЗагрузилась ? (
          <div className="h-full flex flex-col items-center justify-center text-center px-6">
            <div className="text-[44px] mb-3">📡</div>
            <p className="text-[15px] font-semibold mb-1">Не удалось загрузить переписку</p>
            <p className="text-[13.5px] text-text-muted mb-6 max-w-[32ch]">
              Сообщения на месте — не хватило связи. Проверьте соединение.
            </p>
            <Button variant="secondary" size="md" onClick={() => window.location.reload()}>
              Повторить
            </Button>
          </div>
        ) : messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center px-6">
            <div className="text-[44px] mb-3">👋</div>
            <p className="text-[15px] font-semibold mb-1">Вы понравились друг другу</p>
            <p className="text-[13.5px] text-text-muted mb-6 max-w-[32ch]">
              Первое сообщение решает многое. Можно начать с подсказки.
            </p>

            {icebreakers.length > 0 ? (
              <div className="flex flex-col gap-2 w-full max-w-[320px]">
                {icebreakers.map((text) => (
                  <button
                    key={text}
                    onClick={() => send(text)}
                    className="px-4 py-3 rounded-[var(--radius-tile)] bg-surface
                               border border-hairline text-[14px] text-left
                               active:bg-surface-2 transition-colors"
                  >
                    {text}
                  </button>
                ))}
              </div>
            ) : (
              <button
                onClick={loadIcebreakers}
                disabled={loadingIce}
                className="inline-flex items-center gap-2 px-4 h-11 rounded-full
                           bg-surface border border-hairline text-[14px]
                           disabled:opacity-50"
              >
                {loadingIce ? (
                  <Spinner size={16} />
                ) : (
                  <Sparkles size={15} className="text-accent" />
                )}
                Подсказать фразу
              </button>
            )}
          </div>
        ) : (
          <>
            {groups.map((group) => {
              const last = group.messages[group.messages.length - 1];
              return (
                <div key={group.key}>
                  {group.dateLabel && (
                    <div className="flex justify-center my-4">
                      <span className="px-3 py-1 rounded-full bg-surface text-[11.5px] text-text-muted">
                        {group.dateLabel}
                      </span>
                    </div>
                  )}

                  <div
                    className={`flex flex-col gap-0.5 mb-2.5 ${
                      group.mine ? "items-end" : "items-start"
                    }`}
                  >
                    {group.messages.map((m, i) => {
                      const isLast = i === group.messages.length - 1;
                      return (
                        <motion.div
                          key={m.id}
                          initial={{ opacity: 0, y: 6 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ type: "spring", stiffness: 420, damping: 32 }}
                          className={`max-w-[78%] px-3.5 py-2 text-[15px] leading-snug
                                      break-words selectable ${
                                        theme?.bubble_mine_color ||
                                        theme?.bubble_theirs_color
                                          ? ""
                                          : group.mine
                                            ? "bg-accent text-white"
                                            : "bg-surface-2 text-text"
                                      }`}
                          style={{
                            borderRadius: 20,
                            borderBottomRightRadius: group.mine && isLast ? 6 : 20,
                            borderBottomLeftRadius: !group.mine && isLast ? 6 : 20,
                            // Тема задана — красим значением; нет — оставляем
                            // классы выше. Класс и style одновременно дали бы
                            // градиент под сплошным цветом, и на полупрозрачных
                            // цветах он проступал бы полосами.
                            background: group.mine
                              ? theme?.bubble_mine_color || undefined
                              : theme?.bubble_theirs_color || undefined,
                            color: group.mine
                              ? theme?.bubble_mine_color
                                ? readableOn(theme.bubble_mine_color)
                                : undefined
                              : theme?.bubble_theirs_color
                                ? readableOn(theme.bubble_theirs_color)
                                : undefined,
                          }}
                        >
                          {m.reel && <ReelBubble reel={m.reel} mine={group.mine} />}
                          {m.image_url && (
                            <img
                              src={m.image_url}
                              alt=""
                              className="rounded-xl mb-1 max-w-full"
                            />
                          )}
                          {m.text}
                        </motion.div>
                      );
                    })}

                    <div className="flex items-center gap-1 px-1 mt-0.5">
                      <span
                        className="text-[10.5px] text-text-faint"
                        style={{
                          // `text-faint` — фиксированный цвет под базовый фон.
                          // Тема красит фон произвольным, и время на нём
                          // пропадало: берём читаемый по фону.
                          color: theme?.background_color
                            ? readableOn(theme.background_color)
                            : undefined,
                          opacity: theme?.background_color ? 0.6 : undefined,
                        }}
                      >
                        {formatTime(last.created_at, язык)}
                      </span>
                      {group.mine &&
                        (last.read_at ? (
                          <CheckCheck size={13} className="text-info" />
                        ) : (
                          <Check size={13} className="text-text-faint" />
                        ))}
                    </div>
                  </div>
                </div>
              );
            })}

            <AnimatePresence>
              {partnerTyping && (
                <motion.div
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  className="flex gap-1 px-3.5 py-3 rounded-[20px] bg-surface-2 w-fit"
                >
                  {[0, 1, 2].map((i) => (
                    <motion.span
                      key={i}
                      className="w-1.5 h-1.5 rounded-full bg-text-muted"
                      animate={{ opacity: [0.3, 1, 0.3], y: [0, -3, 0] }}
                      transition={{ duration: 1.1, repeat: Infinity, delay: i * 0.16 }}
                    />
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </>
        )}

        <div ref={bottomRef} />
      </div>

      {/* ── Поле ввода ──────────────────────────────────────── */}
      <div className="shrink-0 chrome border-t border-hairline/70 px-3 pt-2.5 pb-2 safe-bottom">
        {sendError && (
          <p className="text-[12px] text-danger text-center mb-2">
            Сообщение не ушло — нет связи. Попробуйте ещё раз.
          </p>
        )}

        {actionError && (
          <button
            onClick={() => setActionError("")}
            className="block mx-auto mb-2 px-4 py-2 rounded-full bg-danger/15
                       border border-danger/30 text-danger text-[13px] font-medium"
          >
            {actionError} · закрыть
          </button>
        )}

        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => onInputChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder="Сообщение…"
            rows={1}
            className="flex-1 max-h-[120px] px-4 py-2.5 rounded-[22px] resize-none
                       bg-surface border border-hairline text-[15px]
                       outline-none focus:border-accent transition-colors
                       placeholder:text-text-faint no-scrollbar"
          />
          <button
            aria-label="Отправить"
            onClick={() => send()}
            disabled={!input.trim()}
            className="w-11 h-11 rounded-full bg-accent text-white shrink-0
                       flex items-center justify-center
                       disabled:opacity-30 active:scale-95 transition-transform"
          >
            <Send size={18} />
          </button>
        </div>
      </div>

      <ReportSheet
        open={reportOpen}
        name={match?.partner.display_name || "этого пользователя"}
        onClose={() => setReportOpen(false)}
        onPick={sendReport}
      />

      <ChatThemeSheet
        open={themeOpen}
        onClose={() => setThemeOpen(false)}
        matchId={matchId!}
        theme={theme}
        onApplied={(t) => {
          setTheme(t);
          setThemeOpen(false);
        }}
        onNeedPlus={() => {
          setThemeOpen(false);
          navigate("/plans");
        }}
      />

      <HabitsSheet open={habitsOpen} onClose={() => setHabitsOpen(false)} />
      <ProfileSheet
        profile={profileOpen ? match?.partner ?? null : null}
        onClose={() => setProfileOpen(false)}
      />
    </div>
  );
}

/* ── Выбор причины жалобы ───────────────────────────────────── */

function ReportSheet({
  open,
  name,
  onClose,
  onPick,
}: {
  open: boolean;
  name: string;
  onClose: () => void;
  onPick: (reason: string) => void;
}) {
  return (
    <AnimatePresence>
      {open && (
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
            aria-label="Причина жалобы"
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", stiffness: 380, damping: 36 }}
            className="fixed bottom-0 left-0 right-0 z-50 bg-bg-elevated
                       rounded-t-[var(--radius-sheet)] border-t border-hairline
                       px-5 pt-3 pb-7 safe-bottom max-h-[80dvh] overflow-y-auto no-scrollbar"
          >
            <div className="w-10 h-1 rounded-full bg-surface-3 mx-auto mb-5" />

            <h2 className="text-heading font-bold mb-1.5">Пожаловаться на {name}</h2>
            <p className="text-caption text-text-muted mb-4">
              Мэтч будет удалён, а жалоба уйдёт модератору
            </p>

            <div className="flex flex-col gap-1.5 mb-4">
              {REPORT_REASONS.map((r) => (
                <button
                  key={r.value}
                  onClick={() => onPick(r.value)}
                  className="w-full px-4 py-3 rounded-[var(--radius-tile)] text-left
                             bg-surface-2 border border-hairline text-[15px]
                             active:bg-surface transition-colors"
                >
                  {r.label}
                </button>
              ))}
            </div>

            <Button variant="secondary" size="lg" fullWidth onClick={onClose}>
              Отмена
            </Button>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

/* ── Группировка ────────────────────────────────────────────── */

interface Group {
  key: string;
  mine: boolean;
  dateLabel: string | null;
  messages: ChatMessage[];
}

/** Подряд идущие сообщения одного автора в пределах 5 минут — одна группа. */
function groupMessages(messages: ChatMessage[], myId: string | undefined, язык: Язык): Group[] {
  const groups: Group[] = [];
  let lastDate = "";

  for (const m of messages) {
    const mine = m.sender_id === myId;
    const dayKey = m.created_at ? new Date(m.created_at).toDateString() : "";
    const dateLabel = dayKey && dayKey !== lastDate ? formatDate(m.created_at, язык) : null;
    if (dateLabel) lastDate = dayKey;

    const prev = groups[groups.length - 1];
    const canAppend =
      prev &&
      prev.mine === mine &&
      !dateLabel &&
      withinGap(prev.messages[prev.messages.length - 1].created_at, m.created_at);

    if (canAppend) {
      prev.messages.push(m);
    } else {
      groups.push({ key: m.id, mine, dateLabel, messages: [m] });
    }
  }

  return groups;
}

function withinGap(a?: string | null, b?: string | null): boolean {
  if (!a || !b) return true;
  const diff = Math.abs(new Date(b).getTime() - new Date(a).getTime());
  return diff < 5 * 60 * 1000;
}

function formatTime(iso: string | null | undefined, язык: Язык): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return форматВремени(d, язык);
}

function formatDate(iso: string | null | undefined, язык: Язык): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";

  const now = new Date();
  if (d.toDateString() === now.toDateString()) return перевести(язык, "date.today");

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return перевести(язык, "date.yesterday");

  // Год добавляем только чужой: «20 августа 2026» в переписке этого года —
  // шум, а без года в переписке прошлого не понять, о каком дне речь.
  return форматДняРазделителя(d, язык, d.getFullYear() !== now.getFullYear());
}
