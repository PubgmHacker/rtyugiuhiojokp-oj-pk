const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const WS_URL = API_URL.replace(/^http/, "ws");

type MessageHandler = (data: any) => void;
export type ConnectionStatus = "connecting" | "open" | "closed";
type StatusHandler = (status: ConnectionStatus) => void;
/** Соединение закрыто окончательно — переподключаться бессмысленно. */
export interface FatalClose {
  code: number;
  reason: string;
}
type CloseHandler = (info: FatalClose) => void;

/**
 * Коды, после которых сервер не примет и десятую попытку: нет токена, чужой
 * чат, мэтч удалён, исчерпан суточный лимит открытых мэтчей. Раньше на все
 * четыре клиент честно ломился восемь раз с нарастающей паузой — впустую
 * гонял сервер по базе и держал баннер «переподключение…» вместо причины.
 * 1000 сюда не входит: это наше собственное закрытие, оно и так не
 * переподключается и слушателей не будит.
 */
const FATAL_CLOSE_CODES = new Set([4001, 4003, 4004, 4029]);

/** Держим соединение живым сквозь таймауты прокси/балансировщиков. */
const HEARTBEAT_INTERVAL = 25_000;
const BASE_RECONNECT_DELAY = 1500;
const MAX_RECONNECT_DELAY = 20_000;
const MAX_RECONNECT_ATTEMPTS = 8;
/** Не растим Set идентификаторов бесконечно в долгих переписках. */
const MAX_SEEN_IDS = 500;

export class ChatWebSocket {
  private ws: WebSocket | null = null;
  private matchId: string;
  private token: string;
  private handlers: Set<MessageHandler> = new Set();
  private openHandlers: Set<() => void> = new Set();
  private statusHandlers: Set<StatusHandler> = new Set();
  private closeHandlers: Set<CloseHandler> = new Set();
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private closed = false;
  private seenIds: Set<string> = new Set();
  private seenOrder: string[] = [];

  constructor(matchId: string, token: string) {
    this.matchId = matchId;
    this.token = token;
    // Вкладка вернулась из фона / сеть восстановилась — это сильный сигнал,
    // что реконнект сейчас, скорее всего, получится, поэтому даём свежий лимит попыток
    window.addEventListener("visibilitychange", this.handleVisibility);
    window.addEventListener("online", this.handleOnline);
  }

  private handleVisibility = () => {
    if (document.visibilityState === "visible" && !this.closed) {
      this.reconnectAttempts = 0;
      this.scheduleReconnect(true);
    }
  };

  private handleOnline = () => {
    if (!this.closed) {
      this.reconnectAttempts = 0;
      this.scheduleReconnect(true);
    }
  };

  connect() {
    if (this.closed) return;
    // Уже открыт или открывается — не плодим параллельные сокеты
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    this.clearReconnectTimer();
    this.statusHandlers.forEach((h) => h("connecting"));

    let socket: WebSocket;
    try {
      socket = new WebSocket(`${WS_URL}/ws/chat/${this.matchId}?token=${this.token}`);
    } catch (e) {
      console.error("[WS] Не удалось создать соединение:", e);
      this.scheduleReconnect();
      return;
    }
    this.ws = socket;

    socket.onopen = () => {
      if (this.ws !== socket) return; // сокет уже заменён/закрыт
      this.reconnectAttempts = 0;
      this.startHeartbeat();
      this.statusHandlers.forEach((h) => h("open"));
      this.openHandlers.forEach((h) => h());
    };

    socket.onmessage = (event) => {
      if (this.ws !== socket) return;
      let data: any;
      try {
        data = JSON.parse(event.data);
      } catch (e) {
        console.error("[WS] Ошибка разбора сообщения:", e);
        return;
      }
      // Дедуп по id — реконнект или повторный broadcast не должны дублировать сообщение в ленте
      if (data?.type === "message" && data?.id) {
        if (this.seenIds.has(data.id)) return;
        this.rememberId(data.id);
      }
      this.handlers.forEach((h) => h(data));
    };

    socket.onclose = (event) => {
      if (this.ws !== socket) return;
      this.stopHeartbeat();
      this.statusHandlers.forEach((h) => h("closed"));
      if (FATAL_CLOSE_CODES.has(event.code)) {
        // Причину знает только сервер — передаём её наверх и больше не
        // пытаемся: интерфейс покажет объяснение вместо «нет связи»
        this.closed = true;
        this.clearReconnectTimer();
        this.closeHandlers.forEach((h) =>
          h({ code: event.code, reason: event.reason })
        );
        return;
      }
      if (!this.closed && event.code !== 1000) {
        this.scheduleReconnect();
      }
    };

    socket.onerror = () => {
      // onclose всегда следует за onerror — реконнект планируется там,
      // чтобы не завести два параллельных таймера на одно и то же событие
    };
  }

  private scheduleReconnect(immediate = false) {
    if (this.closed) return;
    this.clearReconnectTimer();
    if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) return;
    this.reconnectAttempts++;
    const delay = immediate
      ? 0
      : Math.min(BASE_RECONNECT_DELAY * 2 ** (this.reconnectAttempts - 1), MAX_RECONNECT_DELAY);
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }

  private clearReconnectTimer() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private startHeartbeat() {
    this.stopHeartbeat();
    // Пустой text/image_url — бэкенд молча игнорирует такой пакет (см. api/routers/chat.py),
    // так что пинг не создаёт ни сообщений, ни ошибок на сервере
    this.heartbeatTimer = setInterval(() => {
      this.sendRaw({ type: "ping" });
    }, HEARTBEAT_INTERVAL);
  }

  private stopHeartbeat() {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private rememberId(id: string) {
    this.seenIds.add(id);
    this.seenOrder.push(id);
    if (this.seenOrder.length > MAX_SEEN_IDS) {
      const old = this.seenOrder.shift();
      if (old) this.seenIds.delete(old);
    }
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

  /** @returns функция отписки */
  onMessage(handler: MessageHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  /** @returns функция отписки */
  onOpen(handler: () => void): () => void {
    this.openHandlers.add(handler);
    if (this.isOpen()) handler();
    return () => this.openHandlers.delete(handler);
  }

  /** Статус соединения — удобно показать баннер «переподключение…» в интерфейсе. */
  onStatusChange(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler);
    return () => this.statusHandlers.delete(handler);
  }

  /**
   * Окончательное закрытие с кодом сервера — 4001/4003/4004/4029.
   * Вызывается один раз; после него сокет не переподключается.
   * @returns функция отписки
   */
  onFatalClose(handler: CloseHandler): () => void {
    this.closeHandlers.add(handler);
    return () => this.closeHandlers.delete(handler);
  }

  close() {
    this.closed = true;
    this.clearReconnectTimer();
    this.stopHeartbeat();
    window.removeEventListener("visibilitychange", this.handleVisibility);
    window.removeEventListener("online", this.handleOnline);
    if (this.ws) {
      // Дальнейшие события уже закрытого сокета не должны ничего триггерить
      this.ws.onopen = null;
      this.ws.onmessage = null;
      this.ws.onclose = null;
      this.ws.onerror = null;
      this.ws.close(1000, "User closed");
      this.ws = null;
    }
    this.handlers.clear();
    this.openHandlers.clear();
    this.statusHandlers.clear();
    this.closeHandlers.clear();
    this.seenIds.clear();
    this.seenOrder = [];
  }
}
