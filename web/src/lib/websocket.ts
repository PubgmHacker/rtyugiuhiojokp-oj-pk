const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const WS_URL = API_URL.replace(/^http/, "ws");

type MessageHandler = (data: any) => void;

export class ChatWebSocket {
  private ws: WebSocket | null = null;
  private matchId: string;
  private token: string;
  private handlers: Set<MessageHandler> = new Set();
  private reconnectAttempts = 0;
  private maxReconnects = 5;

  constructor(matchId: string, token: string) {
    this.matchId = matchId;
    this.token = token;
  }

  connect() {
    this.ws = new WebSocket(`${WS_URL}/ws/chat/${this.matchId}?token=${this.token}`);

    this.ws.onopen = () => {
      console.log("[WS] Connected to chat", this.matchId);
      this.reconnectAttempts = 0;
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
      if (event.code !== 1000 && this.reconnectAttempts < this.maxReconnects) {
        this.reconnectAttempts++;
        setTimeout(() => this.connect(), 2000 * this.reconnectAttempts);
      }
    };

    this.ws.onerror = (error) => {
      console.error("[WS] Error:", error);
    };
  }

  send(text: string, imageUrl?: string) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ text, image_url: imageUrl }));
    }
  }

  onMessage(handler: MessageHandler) {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  close() {
    this.reconnectAttempts = this.maxReconnects; // prevent reconnect
    this.ws?.close(1000, "User closed");
    this.handlers.clear();
  }
}
