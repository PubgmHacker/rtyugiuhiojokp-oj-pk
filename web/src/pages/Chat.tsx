import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Send, Flag, MoreVertical, Sparkles, UserX, Check, CheckCheck } from "lucide-react";
import {
  getMessages, getMatches, getIcebreakers, reportUser, unmatch,
  type ChatMessage, type MatchResponse,
} from "../lib/api";
import { ChatWebSocket } from "../lib/websocket";
import { useStore } from "../lib/store";
import { hapticFeedback } from "../lib/telegram";

export default function Chat() {
  const { matchId } = useParams<{ matchId: string }>();
  const navigate = useNavigate();
  const { user, token } = useStore();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [match, setMatch] = useState<MatchResponse | null>(null);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [showMenu, setShowMenu] = useState(false);
  const [partnerTyping, setPartnerTyping] = useState(false);
  const [icebreakers, setIcebreakers] = useState<string[]>([]);
  const [loadingIce, setLoadingIce] = useState(false);
  const wsRef = useRef<ChatWebSocket | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const typingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastTypingSent = useRef(0);

  useEffect(() => {
    if (!matchId) return;

    const load = async () => {
      try {
        const [msgs, matchList] = await Promise.all([getMessages(matchId), getMatches()]);
        // Мержим с уже полученными по WS (история может прийти позже сокета)
        setMessages((prev) => {
          const seen = new Set(msgs.map((m) => m.id));
          return [...msgs, ...prev.filter((m) => !seen.has(m.id))];
        });
        setMatch(matchList.find((m) => m.id === matchId) ?? null);
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    };
    load();

    // Connect WebSocket
    if (token) {
      const ws = new ChatWebSocket(matchId, token);
      ws.connect();
      ws.onMessage((data) => {
        if (data.type === "message") {
          setMessages((prev) => (prev.some((m) => m.id === data.id) ? prev : [...prev, data]));
          setPartnerTyping(false);
          hapticFeedback("light");
          // Сообщение от партнёра — сразу отмечаем прочитанным
          if (data.sender_id !== useStore.getState().user?.id) {
            ws.sendRaw({ type: "read" });
          }
        } else if (data.type === "typing") {
          if (data.user_id === useStore.getState().user?.id) return; // своя вторая вкладка
          setPartnerTyping(true);
          if (typingTimer.current) clearTimeout(typingTimer.current);
          typingTimer.current = setTimeout(() => setPartnerTyping(false), 3000);
        } else if (data.type === "read") {
          // Партнёр прочитал — галочки только на НАШИХ сообщениях
          const now = new Date().toISOString();
          const myId = useStore.getState().user?.id;
          setMessages((prev) =>
            prev.map((m) => (m.read_at || m.sender_id !== myId ? m : { ...m, read_at: now }))
          );
        }
      });
      wsRef.current = ws;
      // Отмечаем входящие прочитанными при открытии чата
      ws.onOpen(() => ws.sendRaw({ type: "read" }));
    }

    return () => {
      wsRef.current?.close();
      if (typingTimer.current) clearTimeout(typingTimer.current);
    };
  }, [matchId, token]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, partnerTyping]);

  const [sendError, setSendError] = useState(false);

  const handleSend = useCallback((textOverride?: string) => {
    const text = (textOverride ?? input).trim();
    if (!text || !wsRef.current) return;
    // Сокет мог реконнектиться — не теряем текст и не чистим поле зря
    const sent = wsRef.current.send(text);
    if (!sent) {
      if (textOverride) setInput(textOverride);
      setSendError(true);
      setTimeout(() => setSendError(false), 3000);
      return;
    }
    setInput("");
    setIcebreakers([]);
    hapticFeedback("light");
  }, [input]);

  const handleInputChange = (value: string) => {
    setInput(value);
    // Троттлим typing-события (раз в 2 сек)
    const now = Date.now();
    if (now - lastTypingSent.current > 2000 && wsRef.current) {
      wsRef.current.sendRaw({ type: "typing" });
      lastTypingSent.current = now;
    }
  };

  const handleIcebreakers = async () => {
    if (!matchId || loadingIce) return;
    setLoadingIce(true);
    try {
      setIcebreakers(await getIcebreakers(matchId));
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingIce(false);
    }
  };

  const handleReport = async () => {
    if (!match) return;
    if (!window.confirm(`Пожаловаться на ${match.partner.display_name || "пользователя"}? Мэтч будет удалён.`)) return;
    try {
      await reportUser(match.partner.id, "other", "Жалоба из чата");
      await unmatch(match.id);
      navigate("/matches");
    } catch (e) {
      console.error(e);
    }
  };

  const handleUnmatch = async () => {
    if (!match) return;
    if (!window.confirm("Размэтчиться? Чат будет недоступен обоим.")) return;
    try {
      await unmatch(match.id);
      navigate("/matches");
    } catch (e) {
      console.error(e);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-accent" />
      </div>
    );
  }

  const partnerName = match?.partner.display_name || "Чат";
  const partnerPhoto = match?.partner.photos?.[0];

  return (
    <div className="min-h-screen flex flex-col max-w-md mx-auto">
      {/* Header */}
      <header className="flex items-center gap-3 px-4 py-3 border-b border-surface safe-top">
        <button onClick={() => navigate("/matches")} className="p-1">
          <ArrowLeft size={24} />
        </button>
        {partnerPhoto ? (
          <img src={partnerPhoto} alt="" className="w-9 h-9 rounded-full object-cover" />
        ) : (
          <div className="w-9 h-9 rounded-full bg-surface flex items-center justify-center text-sm">
            {partnerName.slice(0, 1)}
          </div>
        )}
        <div className="flex-1">
          <p className="font-semibold">{partnerName}</p>
          {partnerTyping ? (
            <p className="text-xs text-accent animate-pulse">печатает…</p>
          ) : match?.match_score != null ? (
            <p className="text-xs text-warn">✨ {match.match_score}% совместимость</p>
          ) : null}
        </div>
        <button onClick={() => setShowMenu(!showMenu)} className="p-1 relative">
          <MoreVertical size={24} />
          {showMenu && (
            <div className="absolute right-0 top-10 bg-surface rounded-xl shadow-xl py-2 w-52 z-50">
              <button
                onClick={handleUnmatch}
                className="w-full px-4 py-2 text-text-muted hover:bg-surface/80 flex items-center gap-2"
              >
                <UserX size={16} /> Размэтчиться
              </button>
              <button
                onClick={handleReport}
                className="w-full px-4 py-2 text-danger hover:bg-surface/80 flex items-center gap-2"
              >
                <Flag size={16} /> Пожаловаться
              </button>
            </div>
          )}
        </button>
      </header>

      {/* AI reason banner */}
      {match?.ai_reason && messages.length === 0 && (
        <div className="mx-4 mt-3 px-4 py-3 bg-accent/10 border border-accent/30 rounded-xl text-sm text-accent flex items-start gap-2">
          <Sparkles size={16} className="mt-0.5 shrink-0" />
          <span>{match.ai_reason}</span>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3 no-scrollbar">
        {messages.length === 0 ? (
          <div className="text-center py-16 text-text-muted">
            <p className="mb-4">Напишите первое сообщение!</p>
            <button
              onClick={handleIcebreakers}
              disabled={loadingIce}
              className="inline-flex items-center gap-2 px-4 py-2 bg-accent/20 text-accent rounded-full text-sm font-medium disabled:opacity-50"
            >
              <Sparkles size={16} />
              {loadingIce ? "Придумываю…" : "AI-подсказки для старта"}
            </button>
          </div>
        ) : (
          messages.map((msg) => {
            const isMine = msg.sender_id === user?.id;
            return (
              <div key={msg.id} className={`flex ${isMine ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[75%] px-4 py-2 rounded-2xl ${
                    isMine
                      ? "bg-gradient-to-br from-accent to-warn text-white rounded-br-md"
                      : "bg-surface text-text rounded-bl-md"
                  }`}
                >
                  {msg.image_url && (
                    <img src={msg.image_url} alt="" className="rounded-xl mb-2 max-w-full" />
                  )}
                  {msg.text && <p className="break-words">{msg.text}</p>}
                  <p className={`text-xs mt-1 flex items-center gap-1 justify-end ${isMine ? "text-white/60" : "text-text-muted"}`}>
                    {msg.created_at ? new Date(msg.created_at).toLocaleTimeString("ru", { hour: "2-digit", minute: "2-digit" }) : ""}
                    {isMine && (msg.read_at ? <CheckCheck size={14} /> : <Check size={14} />)}
                  </p>
                </div>
              </div>
            );
          })
        )}
        {partnerTyping && (
          <div className="flex justify-start">
            <div className="px-4 py-3 bg-surface rounded-2xl rounded-bl-md">
              <span className="inline-flex gap-1">
                <span className="w-2 h-2 bg-text-muted rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="w-2 h-2 bg-text-muted rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="w-2 h-2 bg-text-muted rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
              </span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Icebreaker suggestions */}
      {icebreakers.length > 0 && (
        <div className="px-4 pb-2 space-y-2">
          {icebreakers.map((ice, i) => (
            <button
              key={i}
              onClick={() => handleSend(ice)}
              className="w-full text-left px-4 py-2.5 bg-accent/10 border border-accent/30 rounded-xl text-sm hover:bg-accent/20 transition"
            >
              {ice}
            </button>
          ))}
        </div>
      )}

      {/* Send error */}
      {sendError && (
        <div className="mx-4 mb-2 px-4 py-2 bg-danger/20 border border-danger/40 rounded-xl text-danger text-xs">
          Нет соединения — сообщение не отправлено, попробуйте ещё раз
        </div>
      )}

      {/* Input */}
      <div className="flex items-center gap-2 p-4 border-t border-surface safe-bottom">
        <button
          onClick={handleIcebreakers}
          disabled={loadingIce}
          className="w-12 h-12 bg-surface rounded-full flex items-center justify-center text-accent shrink-0 disabled:opacity-40"
          title="AI-подсказки"
        >
          <Sparkles size={20} />
        </button>
        <input
          type="text"
          value={input}
          onChange={(e) => handleInputChange(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          placeholder="Сообщение..."
          className="flex-1 px-4 py-3 bg-surface rounded-full outline-none focus:ring-2 focus:ring-accent min-w-0"
        />
        <button
          onClick={() => handleSend()}
          disabled={!input.trim()}
          className="w-12 h-12 bg-gradient-to-br from-accent to-warn rounded-full flex items-center justify-center disabled:opacity-40 shrink-0"
        >
          <Send size={20} className="text-white" />
        </button>
      </div>
    </div>
  );
}
