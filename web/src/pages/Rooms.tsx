/**
 * Групповые чаты по интересам.
 *
 * Написать в общий чат проще, чем первым в личку, поэтому комнаты закрывают
 * разрыв между «увидел анкету» и «начал разговор».
 *
 * Экран двухрежимный: список комнат и открытая комната. Отдельным маршрутом
 * комнату не делаем — возврат к списку должен быть мгновенным, без перезагрузки.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, Flag, Send, Users } from "lucide-react";
import {
  getRoomMessages,
  getRooms,
  reportRoomMessage,
  sendRoomMessage,
  type Room,
  type RoomMessage,
} from "../lib/api";
import { haptic } from "../lib/haptics";
import { letterAvatarStyle } from "../lib/aura";
import { useSectionOpen } from "../lib/useSectionOpen";
import { useIsMounted } from "../hooks/useSafeAsync";
import {
  Button,
  EmptyState,
  LoadError,
  ScreenHeader,
  Skeleton,
  Spinner,
} from "../components/ui";
import ReelBubble from "../components/ReelBubble";
import ReportReasonSheet from "../components/ReportReasonSheet";

export default function Rooms() {
  useSectionOpen("rooms");
  const [rooms, setRooms] = useState<Room[] | null>(null);
  const [active, setActive] = useState<Room | null>(null);
  // Сбой загрузки и «комнат правда нет» — разные вещи. Раньше ошибка молча
  // превращалась в пустой список, и человек думал, что раздел пустой
  const [сбой, setСбой] = useState(false);

  const загрузить = useCallback(() => {
    setСбой(false);
    setRooms(null);
    getRooms()
      .then(setRooms)
      .catch(() => {
        setRooms([]);
        setСбой(true);
      });
  }, []);

  useEffect(загрузить, [загрузить]);

  if (active) {
    return <RoomChat room={active} onBack={() => setActive(null)} />;
  }

  if (!rooms) {
    return (
      <div>
        <ScreenHeader title="Чаты по интересам" />
        <div className="px-4 pt-4 flex flex-col gap-2.5">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-20 rounded-[var(--radius-tile)]" />
          ))}
        </div>
      </div>
    );
  }

  if (!rooms.length) {
    return (
      <div>
        <ScreenHeader title="Чаты по интересам" />
        <EmptyState
          emoji={сбой ? "📡" : "💬"}
          title={сбой ? "Не удалось загрузить" : "Комнат пока нет"}
          description={
            сбой
              ? "Проверьте соединение и попробуйте снова."
              : "Скоро здесь появятся чаты по темам."
          }
          action={
            сбой ? (
              <Button variant="secondary" size="md" onClick={загрузить}>
                Повторить
              </Button>
            ) : undefined
          }
        />
      </div>
    );
  }

  return (
    <div className="pb-4">
      <ScreenHeader title="Чаты по интересам" />

      <p className="px-4 pt-3 text-[13.5px] text-text-muted">
        Общаться в общем чате проще, чем писать первым в личку.
      </p>

      <div className="px-4 pt-3 flex flex-col gap-2.5">
        {rooms.map((room) => (
          <button
            key={room.id}
            onClick={() => {
              haptic("light");
              setActive(room);
            }}
            className="w-full text-left px-4 py-3.5 rounded-[var(--radius-tile)]
                       bg-surface-2 border border-hairline
                       active:scale-[0.99] transition-transform"
          >
            <div className="flex items-center gap-2 mb-1">
              <span className="font-bold text-[15.5px] flex-1">{room.title}</span>
              {/* Пустая комната без пометки выглядит так же, как живая, и
                  человек уходит, не дождавшись ответа */}
              {room.messages_today > 0 ? (
                <span
                  className="flex items-center gap-1 text-[12px] font-semibold
                             text-accent shrink-0"
                >
                  <Users size={12} />
                  {room.messages_today} за сутки
                </span>
              ) : (
                <span className="text-[12px] text-text-faint shrink-0">тихо</span>
              )}
            </div>
            <p className="text-caption text-text-muted">{room.description}</p>
          </button>
        ))}
      </div>
    </div>
  );
}

/* ── Открытая комната ───────────────────────────────────────── */

function RoomChat({ room, onBack }: { room: Room; onBack: () => void }) {
  const [messages, setMessages] = useState<RoomMessage[] | null>(null);
  const [сбой, setСбой] = useState(false);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reportFor, setReportFor] = useState<RoomMessage | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const isMounted = useIsMounted();
  // Опрос раз в 7с может наложиться сам на себя, если сеть подтормозила:
  // на резолве применяем ответ только самого свежего запроса, иначе более
  // старый может прийти позже и затереть свежий список устаревшим.
  const requestSeqRef = useRef(0);

  const load = useCallback(async () => {
    // В фоне Telegram/WKWebView всё равно не показывает результат, а запросы
    // только будят сеть и батарею. Первый вызов повторится при возвращении.
    if (document.visibilityState === "hidden") return;
    const seq = ++requestSeqRef.current;
    try {
      const page = await getRoomMessages(room.id);
      if (!isMounted() || seq !== requestSeqRef.current) return;
      setСбой(false);
      // Не выбрасываем локально добавленное сообщение, если polling-ответ
      // пересёкся с POST и сервер ещё отдаёт старый срез истории.
      setMessages((current) => {
        if (!current) return page.messages;
        const serverIds = new Set(page.messages.map((message) => message.id));
        return [
          ...page.messages,
          ...current.filter((message) => !serverIds.has(message.id)),
        ];
      });
    } catch {
      if (!isMounted() || seq !== requestSeqRef.current) return;
      // Переписку не трогаем: сбой фонового опроса не должен стирать уже
      // показанные сообщения (опрос сам повторится через 7с). Флаг нужен
      // только первой загрузке — отличить «не приехало» от «пока тихо».
      setСбой(true);
    }
  }, [room.id, isMounted]);

  useEffect(() => {
    void load();
    // Обновляем периодически: держать WebSocket ради общего чата, куда
    // заходят изредка, дороже, чем опрос раз в несколько секунд
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") void load();
    };
    const timer = window.setInterval(refreshWhenVisible, 7000);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [load]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages?.length]);

  const send = useCallback(async () => {
    const trimmed = text.trim();
    if (!trimmed || sending) return;
    setSending(true);
    setError("");
    try {
      const message = await sendRoomMessage(room.id, trimmed);
      if (!isMounted()) return;
      setMessages((cur) => [...(cur ?? []), message]);
      setText("");
      haptic("success");
    } catch (e: any) {
      if (!isMounted()) return;
      haptic("error");
      setError(e?.response?.data?.detail ?? "Не удалось отправить");
    } finally {
      if (isMounted()) setSending(false);
    }
  }, [text, sending, room.id, isMounted]);

  const пожаловаться = useCallback(
    async (reason: string) => {
      const message = reportFor;
      setReportFor(null);
      if (!message) return;
      setError("");
      try {
        await reportRoomMessage(room.id, message.id, reason);
        haptic("success");
        setNotice("Жалоба отправлена — модератор разберётся");
      } catch (e: any) {
        haptic("error");
        setError(e?.response?.data?.detail ?? "Не удалось отправить жалобу");
      }
    },
    [room.id, reportFor]
  );

  return (
    <div className="flex flex-col h-[calc(100dvh-68px)]">
      <header className="chrome safe-top border-b border-hairline/60 shrink-0">
        <div className="flex items-center gap-2 px-3 pb-2.5 min-h-[48px]">
          <button
            aria-label="Назад к списку"
            onClick={() => {
              haptic("light");
              onBack();
            }}
            className="tap-target flex items-center justify-center text-text-secondary"
          >
            <ChevronLeft size={24} />
          </button>
          <div className="flex-1 min-w-0">
            <p className="font-bold text-[16px] truncate">{room.title}</p>
            <p className="text-caption text-text-muted truncate">
              {room.description}
            </p>
          </div>
        </div>
      </header>

      <div
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        aria-label="Сообщения комнаты"
        className="flex-1 overflow-y-auto px-4 py-3 no-scrollbar"
      >
        {!messages ? (
          сбой ? (
            <LoadError onRetry={load} />
          ) : (
            <div className="flex flex-col gap-2">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-12 rounded-[var(--radius-tile)]" />
              ))}
            </div>
          )
        ) : !messages.length ? (
          <p className="text-center text-[14px] text-text-muted py-10">
            Пока тихо. Напишите первым — это заметят.
          </p>
        ) : (
          <div className="flex flex-col gap-2.5">
            {messages.map((m) => (
              <div
                key={m.id}
                className={`flex gap-2.5 ${m.is_mine ? "flex-row-reverse" : ""}`}
              >
                {!m.is_mine &&
                  (m.sender_photo ? (
                    <img
                      src={m.sender_photo}
                      alt=""
                      loading="lazy"
                      className="w-8 h-8 rounded-full object-cover shrink-0"
                    />
                  ) : (
                    <span
                      className="w-8 h-8 rounded-full shrink-0 flex items-center
                                 justify-center text-[12px] font-bold"
                      style={letterAvatarStyle(m.sender_id)}
                    >
                      {m.sender_name?.[0]?.toUpperCase() ?? "?"}
                    </span>
                  ))}

                <div
                  className={`max-w-[76%] px-3.5 py-2 rounded-[var(--radius-tile)] ${
                    m.is_mine
                      ? "bg-accent text-white"
                      : "bg-surface-2 border border-hairline"
                  }`}
                >
                  {!m.is_mine && (
                    <p className="text-[12px] font-semibold text-accent mb-0.5">
                      {m.sender_name || "Без имени"}
                    </p>
                  )}
                  {m.reel && <ReelBubble reel={m.reel} mine={m.is_mine} />}
                  <p className="text-[14.5px] leading-snug break-words selectable">
                    {m.text}
                  </p>
                </div>

                {/* Жалоба — на каждой поверхности с чужим контентом (App
                    Store, Guideline 1.2). Блокировка убирает обидчика только
                    из своей ленты, а тут его читают все. */}
                {!m.is_mine && (
                  <button
                    aria-label="Пожаловаться на сообщение"
                    onClick={() => {
                      haptic("light");
                      setReportFor(m);
                    }}
                    className="self-center shrink-0 text-text-faint
                               active:scale-90 transition-transform"
                  >
                    <Flag size={14} />
                  </button>
                )}
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {error && (
        <p
          role="alert"
          className="mx-4 mb-2 px-3.5 py-2 rounded-[var(--radius-tile)]
                     bg-danger/12 border border-danger/30 text-danger text-[13px]"
        >
          {error}
        </p>
      )}

      {notice && (
        <p
          role="status"
          className="mx-4 mb-2 px-3.5 py-2 rounded-[var(--radius-tile)]
                     bg-surface-2 border border-hairline text-text-secondary text-[13px]"
        >
          {notice}
        </p>
      )}

      <div className="shrink-0 px-3 pb-3 pt-2 border-t border-hairline/60 safe-bottom">
        <div className="flex items-end gap-2">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value.slice(0, 500))}
            rows={1}
            placeholder="Сообщение"
            aria-label="Сообщение в комнату"
            className="flex-1 px-3.5 py-2.5 rounded-[var(--radius-tile)] resize-none
                       bg-surface-2 border border-hairline text-[15px] max-h-24
                       placeholder:text-text-muted focus:outline-none
                       focus:border-accent/60"
          />
          <button
            aria-label="Отправить"
            onClick={send}
            disabled={!text.trim() || sending}
            className="w-11 h-11 rounded-full bg-accent text-white shrink-0
                       flex items-center justify-center
                       disabled:opacity-30 active:scale-95 transition-transform"
          >
            {sending ? <Spinner size={17} /> : <Send size={18} />}
          </button>
        </div>
      </div>

      <ReportReasonSheet
        open={reportFor !== null}
        title={`Пожаловаться${reportFor?.sender_name ? ` на ${reportFor.sender_name}` : ""}`}
        subtitle="Модератор прочитает сообщение. Три жалобы снимают его с показа для всех."
        onClose={() => setReportFor(null)}
        onPick={пожаловаться}
      />
    </div>
  );
}
