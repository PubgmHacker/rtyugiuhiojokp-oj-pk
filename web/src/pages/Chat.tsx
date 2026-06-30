import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { ArrowLeft, Send, Flag, MoreVertical } from "lucide-react";
import { getMessages, type ChatMessage } from "../lib/api";
import { ChatWebSocket } from "../lib/websocket";
import { useStore } from "../lib/store";
import { hapticFeedback } from "../lib/telegram";

export default function Chat() {
  const { matchId } = useParams<{ matchId: string }>();
  const navigate = useNavigate();
  const { user, token } = useStore();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [showMenu, setShowMenu] = useState(false);
  const wsRef = useRef<ChatWebSocket | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!matchId) return;

    const loadMsgs = async () => {
      try {
        const data = await getMessages(matchId);
        setMessages(data);
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    };
    loadMsgs();

    // Connect WebSocket
    if (token) {
      const ws = new ChatWebSocket(matchId, token);
      ws.connect();
      ws.onMessage((data) => {
        if (data.type === "message") {
          setMessages((prev) => [...prev, data]);
          hapticFeedback("light");
        }
      });
      wsRef.current = ws;
    }

    return () => {
      wsRef.current?.close();
    };
  }, [matchId, token]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text || !wsRef.current) return;
    wsRef.current.send(text);
    setInput("");
    hapticFeedback("light");
  }, [input]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-accent" />
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col max-w-md mx-auto">
      {/* Header */}
      <header className="flex items-center gap-3 px-4 py-3 border-b border-surface safe-top">
        <button onClick={() => navigate("/matches")} className="p-1">
          <ArrowLeft size={24} />
        </button>
        <div className="flex-1">
          <p className="font-semibold">Чат</p>
          <p className="text-xs text-success">● В сети</p>
        </div>
        <button onClick={() => setShowMenu(!showMenu)} className="p-1 relative">
          <MoreVertical size={24} />
          {showMenu && (
            <div className="absolute right-0 top-10 bg-surface rounded-xl shadow-xl py-2 w-48 z-50">
              <Link
                to="/matches"
                className="block px-4 py-2 text-danger hover:bg-surface/80 flex items-center gap-2"
              >
                <Flag size={16} /> Пожаловаться
              </Link>
            </div>
          )}
        </button>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3 no-scrollbar">
        {messages.length === 0 ? (
          <div className="text-center py-20 text-text-muted">
            <p>Напишите первое сообщение!</p>
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
                  <p className={`text-xs mt-1 ${isMine ? "text-white/60" : "text-text-muted"}`}>
                    {msg.created_at ? new Date(msg.created_at).toLocaleTimeString("ru", { hour: "2-digit", minute: "2-digit" }) : ""}
                  </p>
                </div>
              </div>
            );
          })
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="flex items-center gap-2 p-4 border-t border-surface safe-bottom">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          placeholder="Сообщение..."
          className="flex-1 px-4 py-3 bg-surface rounded-full outline-none focus:ring-2 focus:ring-accent"
        />
        <button
          onClick={handleSend}
          disabled={!input.trim()}
          className="w-12 h-12 bg-gradient-to-br from-accent to-warn rounded-full flex items-center justify-center disabled:opacity-40"
        >
          <Send size={20} className="text-white" />
        </button>
      </div>
    </div>
  );
}
