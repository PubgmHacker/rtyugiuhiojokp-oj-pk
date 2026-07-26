const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const WS_URL = API_URL.replace(/^http/, "ws");

type MessageHandler = (data: any) => void;

export class ChatWebSocket {
  private ws: WebSocket | null = null;
  private matchId: string;
  private token: string;
  private handlers: Set<MessageHandler> = new Set();
  private openHandlers: Set<() => void> = new Set();
  private reconnectAttempts = 0;
  private maxReconnects = 5;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private closed = false;

  constructor(matchId: string, token: string) {
    this.matchId = matchId;
    this.token = token;
  }

  connect() {
    this.ws = new WebSocket(`${WS_URL}/ws/chat/${this.matchId}?token=${this.token}`);

    this.ws.onopen = () => {
      console.log("[WS] Connected to chat", this.matchId);
      this.reconnectAttempts = 0;
      this.openHandlers.forEach((h) => h());
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this.handlers.forEach((h) => h(data));
      } catch (e) {
        console.error("[WS] Parse error:", e);
      }
    };

    this.ws.onclose = (event) => {
      console.log("[WS] Closed:", event.code, event.reason);
      if (!this.closed && event.code !== 1000 && this.reconnectAttempts < this.maxReconnects) {
        this.reconnectAttempts++;
        this.reconnectTimer = setTimeout(() => this.connect(), 2000 * this.reconnectAttempts);
      }
    };

    this.ws.onerror = (error) => {
      console.error("[WS] Error:", error);
    };
  }

  isOpen(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  /** @returns true, если сообщение реально ушло в сокет */
  send(text: string, imageUrl?: string): boolean {
    return this.sendRaw({ type: "message", text, image_url: imageUrl });
  }

  sendRaw(payload: Record<string, unknown>): boolean {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
      return true;
    }
    return false;
  }

  onMessage(handler: MessageHandler) {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  onOpen(handler: () => void) {
    this.openHandlers.add(handler);
    if (this.ws?.readyState === WebSocket.OPEN) handler();
  }

  close() {
    this.closed = true;
    this.reconnectAttempts = this.maxReconnects; // prevent reconnect
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer); // иначе отложенный connect() создаст зомби-сокет
      this.reconnectTimer = null;
    }
    this.ws?.close(1000, "User closed");
    this.handlers.clear();
    this.openHandlers.clear();
  }
}
