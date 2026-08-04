import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft,
  Send,
  MoreVertical,
  Sparkles,
  Flag,
  Ban,
  UserX,
  Check,
  CheckCheck,
} from "lucide-react";
import {
  getMessages,
  getMatches,
  getIcebreakers,
  reportUser,
  blockUser,
  unmatch,
  type ChatMessage,
  type MatchResponse,
} from "../lib/api";
import { ChatWebSocket, type ConnectionStatus } from "../lib/websocket";
import { useStore } from "../lib/store";
import { haptic } from "../lib/haptics";
import { Skeleton, Spinner, VerifiedBadge } from "../components/ui";

export default function Chat() {
  const { matchId } = useParams<{ matchId: string }>();
  const navigate = useNavigate();
  const { token } = useStore();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [match, setMatch] = useState<MatchResponse | null>(null);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [menuOpen, setMenuOpen] = useState(false);
  const [partnerTyping, setPartnerTyping] = useState(false);
  const [icebreakers, setIcebreakers] = useState<string[]>([]);
  const [loadingIce, setLoadingIce] = useState(false);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [sendError, setSendError] = useState(false);

  const wsRef = useRef<ChatWebSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const typingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastTypingSent = useRef(0);

  const myId = useStore((s) => s.user?.id);

  /* ── Загрузка истории и сокет ────────────────────────────── */
  useEffect(() => {
    if (!matchId) return;

    (async () => {
      try {
        const [msgs, matchList] = await Promise.all([
          getMessages(matchId),
          getMatches(),
        ]);
        // История может прийти позже сокета — мержим без дублей
        setMessages((prev) => {
          const seen = new Set(msgs.map((m) => m.id));
          return [...msgs, ...prev.filter((m) => !seen.has(m.id))];
        });
        setMatch(matchList.find((m) => m.id === matchId) ?? null);
      } catch {
        /* экран покажет пустую переписку */
      } finally {
        setLoading(false);
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

    ws.connect();

    return () => {
      offStatus();
      offMessage();
      offOpen();
      ws.close();
      wsRef.current = null;
      if (typingTimer.current) clearTimeout(typingTimer.current);
    };
  }, [matchId, token]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, partnerTyping]);

  /* ── Отправка ────────────────────────────────────────────── */
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

  const handleReport = useCallback(async () => {
    if (!match) return;
    const name = match.partner.display_name || "этого пользователя";
    if (!window.confirm(`Пожаловаться на ${name}? Мэтч будет удалён.`)) return;
    try {
      await reportUser(match.partner.id, "other", "Жалоба из чата");
      await unmatch(match.id);
      haptic("success");
      navigate("/matches", { replace: true });
    } catch {
      haptic("error");
    }
  }, [match, navigate]);

  const handleBlock = useCallback(async () => {
    if (!match) return;
    const name = match.partner.display_name || "этого пользователя";
    if (
      !window.confirm(
        `Заблокировать ${name}?\n\nВы больше не увидите друг друга и не сможете связаться. Отменить можно в настройках профиля.`
      )
    )
      return;
    try {
      await blockUser(match.partner.id);
      haptic("success");
      navigate("/matches", { replace: true });
    } catch {
      haptic("error");
    }
  }, [match, navigate]);

  const handleUnmatch = useCallback(async () => {
    if (!match) return;
    if (!window.confirm("Разорвать мэтч? Чат исчезнет у обоих.")) return;
    try {
      await unmatch(match.id);
      haptic("medium");
      navigate("/matches", { replace: true });
    } catch {
      haptic("error");
    }
  }, [match, navigate]);

  /* ── Группировка сообщений ───────────────────────────────── */
  const groups = useMemo(() => groupMessages(messages, myId), [messages, myId]);

  const partnerName = match?.partner.display_name || "Чат";
  const partnerPhoto = match?.partner.photos?.[0];

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

          <div className="w-9 h-9 rounded-full overflow-hidden bg-surface-2 shrink-0">
            {partnerPhoto ? (
              <img src={partnerPhoto} alt="" className="w-full h-full object-cover" />
            ) : (
              <div
                className="w-full h-full flex items-center justify-center text-[14px] font-bold text-white/70"
                style={{ background: "var(--gradient-placeholder)" }}
              >
                {partnerName[0]?.toUpperCase()}
              </div>
            )}
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="font-semibold text-[15px] truncate">{partnerName}</span>
              {match?.partner.is_verified && <VerifiedBadge size={14} />}
            </div>
            <p className="text-[11.5px] text-text-muted truncate">
              {partnerTyping
                ? "печатает…"
                : status === "open"
                  ? "в сети"
                  : status === "connecting"
                    ? "подключение…"
                    : "нет связи"}
            </p>
          </div>

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
                        handleReport();
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
            <p className="text-[12px] text-warn text-center">
              {status === "connecting" ? "Переподключение…" : "Нет связи с чатом"}
            </p>
          </div>
        )}
      </header>

      {/* ── Лента сообщений ─────────────────────────────────── */}
      <div className="flex-1 min-h-0 overflow-y-auto no-scrollbar px-3 py-3">
        {loading ? (
          <div className="flex flex-col gap-3">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton
                key={i}
                className={`h-11 ${i % 2 ? "w-2/3 ml-auto" : "w-1/2"} rounded-[18px]`}
              />
            ))}
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
                                        group.mine
                                          ? "bg-dawn text-white"
                                          : "bg-surface-2 text-text"
                                      }`}
                          style={{
                            borderRadius: 20,
                            borderBottomRightRadius: group.mine && isLast ? 6 : 20,
                            borderBottomLeftRadius: !group.mine && isLast ? 6 : 20,
                          }}
                        >
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
                      <span className="text-[10.5px] text-text-faint">
                        {formatTime(last.created_at)}
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
            className="w-11 h-11 rounded-full bg-dawn text-white shrink-0
                       flex items-center justify-center
                       disabled:opacity-30 active:scale-95 transition-transform"
          >
            <Send size={18} />
          </button>
        </div>
      </div>
    </div>
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
function groupMessages(messages: ChatMessage[], myId?: string): Group[] {
  const groups: Group[] = [];
  let lastDate = "";

  for (const m of messages) {
    const mine = m.sender_id === myId;
    const dayKey = m.created_at ? new Date(m.created_at).toDateString() : "";
    const dateLabel = dayKey && dayKey !== lastDate ? formatDate(m.created_at) : null;
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

function formatTime(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

function formatDate(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";

  const now = new Date();
  if (d.toDateString() === now.toDateString()) return "Сегодня";

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return "Вчера";

  return d.toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "long",
    year: d.getFullYear() === now.getFullYear() ? undefined : "numeric",
  });
}
