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
import { ChevronLeft, Send, Users } from "lucide-react";
import {
  getRoomMessages,
  getRooms,
  sendRoomMessage,
  type Room,
  type RoomMessage,
} from "../lib/api";
import { haptic } from "../lib/haptics";
import { useSectionOpen } from "../lib/useSectionOpen";
import { useIsMounted } from "../hooks/useSafeAsync";
import { EmptyState, ScreenHeader, Skeleton, Spinner } from "../components/ui";
import ReelBubble from "../components/ReelBubble";

export default function Rooms() {
  useSectionOpen("rooms");
  const [rooms, setRooms] = useState<Room[] | null>(null);
  const [active, setActive] = useState<Room | null>(null);

  useEffect(() => {
    getRooms()
      .then(setRooms)
      .catch(() => setRooms([]));
  }, []);

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
          emoji="💬"
          title="Комнат пока нет"
          description="Скоро здесь появятся чаты по темам."
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
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const isMounted = useIsMounted();
  // Опрос раз в 7с может наложиться сам на себя, если сеть подтормозила:
  // на резолве применяем ответ только самого свежего запроса, иначе более
  // старый может прийти позже и затереть свежий список устаревшим.
  const requestSeqRef = useRef(0);

  const load = useCallback(async () => {
    const seq = ++requestSeqRef.current;
    try {
      const page = await getRoomMessages(room.id);
      if (!isMounted() || seq !== requestSeqRef.current) return;
      setMessages(page.messages);
    } catch {
      if (!isMounted() || seq !== requestSeqRef.current) return;
      setMessages([]);
    }
  }, [room.id, isMounted]);

  useEffect(() => {
    load();
    // Обновляем периодически: держать WebSocket ради общего чата, куда
    // заходят изредка, дороже, чем опрос раз в несколько секунд
    const timer = window.setInterval(load, 7000);
    return () => window.clearInterval(timer);
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
      setMessages((cur) => [...(cur ?? []), message]);
      setText("");
      haptic("success");
    } catch (e: any) {
      haptic("error");
      setError(e?.response?.data?.detail ?? "Не удалось отправить");
    } finally {
      setSending(false);
    }
  }, [text, sending, room.id]);

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

      <div className="flex-1 overflow-y-auto px-4 py-3 no-scrollbar">
        {!messages ? (
          <div className="flex flex-col gap-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-12 rounded-[var(--radius-tile)]" />
            ))}
          </div>
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
                                 justify-center text-[12px] font-bold text-white/50"
                      style={{ background: "var(--gradient-placeholder)" }}
                    >
                      {m.sender_name?.[0]?.toUpperCase() ?? "?"}
                    </span>
                  ))}

                <div
                  className={`max-w-[76%] px-3.5 py-2 rounded-[var(--radius-tile)] ${
                    m.is_mine
                      ? "bg-dawn text-white"
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
            className="w-11 h-11 rounded-full bg-dawn text-white shrink-0
                       flex items-center justify-center
                       disabled:opacity-30 active:scale-95 transition-transform"
          >
            {sending ? <Spinner size={17} /> : <Send size={18} />}
          </button>
        </div>
      </div>
    </div>
  );
}
