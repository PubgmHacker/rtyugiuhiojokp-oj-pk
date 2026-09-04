import axios from "axios";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

const api = axios.create({
  baseURL: `${API_URL}/api`,
  timeout: 15000,
});

// Inject JWT token on every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("sd_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

/** Машинный код бана в теле ответа — тот же литерал в api/middleware/auth.py. */
export const КОД_БАНА = "account_banned";

// Автовыход на 401, экран блокировки на бан
api.interceptors.response.use(
  (res) => res,
  (error) => {
    const код = error.response?.status;

    if (код === 401) {
      localStorage.removeItem("sd_token");
      localStorage.removeItem("sd_user");
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    } else if (код === 403 && error.response?.data?.code === КОД_БАНА) {
      // Отличаем по коду, а не по самому 403: тем же кодом отвечают все гейты
      // тарифов («доступно на Plus»), и уводить с апсейла на экран блокировки
      // было бы хуже, чем не делать ничего.
      //
      // Токен намеренно не гасим. Во-первых, экран блокировки показывает, какой
      // именно аккаунт закрыт, — по нему человек пишет в поддержку. Во-вторых,
      // выкидывать на вход значит сказать «аккаунта нет», а он есть, и после
      // разбора он должен открыться без повторного входа.
      //
      // Срок бана кладём рядом со снимком аккаунта: экран блокировки запросов
      // не делает (любой вернулся бы тем же 403) и берёт срок отсюда.
      // Отсутствие срока в ответе — вечный бан, ключ убираем.
      try {
        const до = error.response?.data?.banned_until;
        if (до) localStorage.setItem("sd_banned_until", String(до));
        else localStorage.removeItem("sd_banned_until");
      } catch {
        // приватный режим: без срока экран покажет «бессрочная»
      }
      if (window.location.pathname !== "/banned") {
        window.location.href = "/banned";
      }
    }

    return Promise.reject(error);
  }
);

export default api;

// ── Types ──────────────────────────────────────────────────────

export interface UserProfile {
  id: string;
  telegram_id?: number | null;
  role?: string;
  is_banned?: boolean;
  is_verified?: boolean;
  /** Аккаунт команды Симпа: сервер считает его из роли (utils.официальный).
      Клиент рисует золотой бейдж — чтобы «поддержку» нельзя было сыграть
      одним именем. */
  is_official?: boolean;
  display_name: string;
  bio: string;
  gender: string;
  age?: number | null;
  city: string;
  photos: string[];
  /** Видеоролики анкеты — дополнение к фото, показываются после них. */
  videos?: string[];
  interests: string[];
  ai_bio?: string | null;
  looking_for: string;
  is_incognito: boolean;
  // Пауза: анкета убрана из выдачи по своей воле. Приходит только в своей
  // анкете (/auth/me и /profiles/me) — чужую паузу сервер не отдаёт.
  is_paused?: boolean;
  hide_age?: boolean;
  hide_distance?: boolean;
  hide_from_visitors?: boolean;
  /** Не участвовать в оценке фото — ни оценивать, ни быть оценённым. */
  hide_from_ratings?: boolean;
  is_premium?: boolean;
  age_min?: number;
  age_max?: number;
  distance_max?: number;
  // Нишевые поля анкеты и фильтры по ним: пусто — не указано / не фильтруем
  goal?: string;
  subculture?: string;
  // Тип связи («с кем») — отдельная ось от goal («зачем»)
  relation_type?: string;
  mbti?: string;
  height_cm?: number | null;
  filter_goal?: string;
  filter_subculture?: string;
  filter_relation_type?: string;
  filter_city?: string;
  filter_height_min?: number | null;
  filter_height_max?: number | null;
  /** «Только подтверждённые» в выдаче — защитный фильтр, без гейта по тарифу. */
  filter_verified?: boolean;
  /** Только в списке «кто меня лайкнул»: текст, приложенный к лайку. */
  like_message?: string;
  /** Карточка скрыта до подписки: имени и фото в ответе нет. */
  is_locked?: boolean;
  has_location?: boolean;
  /** Привязанная почта для восстановления доступа. */
  email?: string | null;
  /** Путь к картинке выбранной наклейки; собирает сервер. */
  sticker?: string | null;
  /** Код рамки карточки из кейсов; пусто — рамки нет. */
  decor?: string | null;
  /** Схема оформления приложения: переезжает с человеком между устройствами. */
  app_theme?: string;
  /**
   * Язык интерфейса — код из `ЯЗЫКИ` в lib/i18n. Приезжает уже в ответе на
   * вход, а не отдельным запросом: мини-апп выбирает язык до первой отрисовки,
   * и лишний круг успел бы мигнуть русским тому, кто выбрал другой язык.
   * Живёт на аккаунте, а не на анкете, поэтому есть и во время онбординга.
   */
  locale?: string;
  invited_count?: number;
  referral_boost?: boolean;
  referral_target?: number;
  referral_boost_percent?: number;
  /** Голый username Telegram-канала (без @ и без ссылки) — ссылку собирает клиент. */
  tg_channel?: string | null;
  /** Был в сети недавно — тот же флаг, что в деке. Точного времени сервер
   *  не отдаёт: это была бы слежка. Приходит в «кто лайкнул». */
  is_online?: boolean;
}

export interface DeckProfile {
  id: string;
  display_name: string;
  age?: number | null;
  city: string;
  bio: string;
  photos: string[];
  /** Видеоролики анкеты — карточка показывает их после фото. */
  videos?: string[];
  interests: string[];
  ai_bio?: string | null;
  distance?: number | null;
  match_score?: number | null;
  match_reason?: string | null;
  goal?: string;
  subculture?: string;
  relation_type?: string;
  mbti?: string;
  height_cm?: number | null;
  /** Был в сети недавно. Точное время сервер не отдаёт — это была бы слежка. */
  is_online?: boolean;
  /** Путь к картинке выбранной наклейки. */
  sticker?: string | null;
  /** Код рамки карточки; пусто — рамки нет. */
  decor?: string | null;
  /** Профиль прошёл живую проверку лица — галочка на карточке. */
  is_verified?: boolean;
  /** Аккаунт команды Симпа — золотой бейдж вместо синей галочки. */
  is_official?: boolean;
}

export interface MatchResponse {
  id: string;
  match_score?: number | null;
  ai_reason?: string | null;
  created_at?: string | null;
  partner: UserProfile;
  /** Превью для списка чатов — приходит вместе со списком мэтчей. */
  last_message?: string | null;
  last_message_at?: string | null;
  unread_count?: number;
  /** "match" — взаимный лайк, "direct" — платное письмо без взаимности. */
  kind?: "match" | "direct";
  /** Кто написал первым в "direct"-беседе. */
  initiator_id?: string | null;
  /** Ответил ли получатель на "direct"-письмо. */
  direct_answered?: boolean;

  // Серия общения (огонёк): приходит с пакетом в списке чатов, поэтому
  // рядом храним и emoji — клиенту нечего вычислять по дням самому.
  streak_days?: number;
  streak_emoji?: string;
  streak_revives_left?: number;
  streak_can_revive?: boolean;

  /** Мэтч за суточным лимитом бесплатного уровня. Сервер уже вычистил имя,
      фото и превью переписки — показывать нечего, кроме замка. Счётчик
      непрочитанных остаётся: он честный и он же повод оформить подписку. */
  locked?: boolean;
}

/** Пересланный ролик внутри сообщения — одна форма в личке и в комнате. */
export interface ReelPreview {
  id: string;
  video_url: string;
  cover_url: string;
  caption: string;
}

/** Одно сообщение переписки. */
/** Голосовое или видеокружок в сообщении. Форма кружка — код из noteShapes. */
export interface ChatMedia {
  url: string;
  kind: "voice" | "video_note";
  /** Секунды, 0 — неизвестно. */
  duration: number;
  shape?: string | null;
  /** Столбики волны голосового: цифры 0–9, до 64 штук. */
  waveform?: string | null;
  /** Постер видеокружка — первый кадр записи, лежит рядом с видео. */
  poster?: string | null;
}

/**
 * Цитата над ответом. Имени автора здесь нет намеренно: в личке двое, и
 * клиент знает обоих по sender_id — лишний JOIN на каждое сообщение
 * страницы стоил бы дороже, чем экономит.
 */
export interface MessageQuote {
  id: string;
  sender_id: string;
  text: string;
  kind: "text" | "photo" | "reel" | "voice" | "video_note";
  /** Форма и кадр — только у видеокружка: без них цитата выглядит пустой. */
  shape?: string | null;
  poster?: string | null;
  image_url?: string | null;
  duration: number;
}

/**
 * Реакция на сообщение. Сервер отдаёт список авторов, а не пару
 * {count, mine}: одно и то же событие уходит обоим собеседникам, и «моя»
 * у них разная — считать её на сервере значило бы слать два разных кадра
 * в один чат. Счётчик и «моя» выводит клиент.
 */
export interface MessageReaction {
  key: string;
  users: string[];
}

export interface ChatMessage {
  id: string;
  match_id: string;
  sender_id: string;
  text: string;
  image_url?: string | null;
  reel?: ReelPreview | null;
  media?: ChatMedia | null;
  reply_to?: MessageQuote | null;
  reactions?: MessageReaction[];
  read_at?: string | null;
  created_at: string;
}

// ── API Functions ──────────────────────────────────────────────

export async function authWithTelegram(initData: string): Promise<{ token: string; user: UserProfile }> {
  // Таймаут длиннее инстансного: холодный старт Railway с миграциями
  // занимает дольше 15 секунд, и обрыв по таймауту здесь выглядит у
  // человека как «не удалось войти» без объяснений
  const { data } = await api.post("/auth/telegram", { initData }, { timeout: 30000 });
  // Сервер отвечает success:false статусом 200 (пустой initData и т.п.).
  // Без этой проверки пустой токен сохранялся бы в store, Protected
  // возвращал бы на /login, авто-вход запускался бы снова — цикл
  // перезагрузок вместо одного честного сообщения об ошибке
  if (!data.success || !data.token) {
    throw new Error("Telegram не передал данные входа. Откройте приложение через бота ещё раз");
  }
  return { token: data.token, user: data.user };
}

/** Вход по одноразовому коду из бота (команда /link) — путь для iOS-приложения,
 *  где Telegram initData недоступен. */
export async function authWithLinkCode(code: string): Promise<{ token: string; user: UserProfile }> {
  const { data } = await api.post("/auth/link", { code }, { timeout: 30000 });
  if (!data.success) throw new Error("Неверный или устаревший код");
  return { token: data.token, user: data.user };
}

/** Шаг 1 привязки почты: запросить код. В аккаунт почта пока не пишется. */
export async function attachEmail(email: string): Promise<void> {
  await api.post("/auth/email/attach", { email });
}

/** Шаг 2: подтвердить код — только теперь почта привязывается. */
export async function confirmEmail(email: string, code: string): Promise<{ email: string }> {
  const { data } = await api.post("/auth/email/confirm", { email, code });
  return data;
}

/** Потерян Telegram: попросить код входа на привязанную почту. */
export async function requestEmailRecovery(email: string): Promise<void> {
  await api.post("/auth/email/request", { email });
}

/** Вход по коду с почты. */
export async function loginByEmail(
  email: string,
  code: string
): Promise<{ token: string; user: UserProfile }> {
  const { data } = await api.post("/auth/email/login", { email, code }, { timeout: 30000 });
  if (!data.success) throw new Error("Код неверный или устарел");
  return { token: data.token, user: data.user };
}

export async function getMyProfile(): Promise<UserProfile> {
  const { data } = await api.get("/profiles/me");
  return data;
}

export async function updateMyProfile(patch: Partial<UserProfile> & Record<string, unknown>): Promise<UserProfile> {
  const { data } = await api.patch("/profiles/me", patch);
  return data;
}

export async function getDeck(limit = 10): Promise<DeckProfile[]> {
  const { data } = await api.get(`/profiles/deck?limit=${limit}`);
  return data;
}

export async function resetDeck(): Promise<void> {
  await api.post("/profiles/deck/reset");
}

// ── Верификация профиля (галочка) ──────────────────────────────

/** Код позы задания. Подписи к позам живут в VerificationSheet. */
export type VerificationPose = "straight" | "left" | "right" | "up" | "smile";

export interface VerificationChallenge {
  id: string;
  poses: VerificationPose[];
  /** Секунд до истечения задания. */
  expires_in: number;
}

export interface VerificationStatus {
  is_verified: boolean;
  /** Сколько неудачных попыток осталось на сегодня. */
  attempts_left: number;
  /** Есть ли фото в анкете — без него сравнивать не с чем. */
  has_photo: boolean;
  /** Кто проверяет: "builtin" — позы + AI на сервере, "sumsub" — WebSDK провайдера. */
  provider: "builtin" | "sumsub";
  /** Есть начатая провайдерская попытка без вердикта — стоит сразу опросить finalize. */
  provider_pending: boolean;
  challenge: VerificationChallenge | null;
}

export async function getVerificationStatus(): Promise<VerificationStatus> {
  const { data } = await api.get("/verification/status");
  return data;
}

export async function requestVerificationChallenge(): Promise<
  VerificationChallenge & { attempts_left: number }
> {
  const { data } = await api.post("/verification/challenge");
  return data;
}

/** Отправить кадры по заданию. Сервер их не сохраняет — только вердикт.
 *  Таймаут длиннее обычного: AI разбирает четыре изображения. */
export async function submitVerification(
  frames: Blob[]
): Promise<{ verified: boolean }> {
  const form = new FormData();
  frames.forEach((f, i) => form.append("frames", f, `frame-${i}.jpg`));
  const { data } = await api.post("/verification/submit", form, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 60000,
  });
  return data;
}

/** Токен для WebSDK Sumsub (провайдерский режим). Заводит попытку на сервере. */
export async function requestSumsubToken(): Promise<{
  token: string;
  expires_in: number;
  attempts_left: number;
}> {
  const { data } = await api.post("/verification/sumsub/token");
  return data;
}

/** Опрос вердикта провайдера: зовём после WebSDK, пока не решится.
 *  200 {verified} — галочка; 200 {pending} — ещё думает; 422 — отказ с причиной. */
export async function finalizeSumsub(): Promise<{
  verified?: boolean;
  pending?: boolean;
}> {
  const { data } = await api.post("/verification/sumsub/finalize", undefined, {
    // Внутри сервер ходит к Sumsub и сверяет лицо — дольше обычного запроса
    timeout: 45000,
  });
  return data;
}

/** Счётчики для бейджей таббара. Лёгкий: три числа вместо трёх списков. */
export interface BadgeCounts {
  messages: number;
  likes: number;
  /** Красная точка колокольчика — непрочитанное в центре уведомлений. */
  notifications: number;
}

export async function getBadges(): Promise<BadgeCounts> {
  const { data } = await api.get("/badges");
  return data;
}

/** Событие центра уведомлений. Текст собирает клиент из kind+payload:
 *  API не знает языка интерфейса. Неизвестный kind — молча спрятать
 *  (старый клиент переживает новые виды событий без «undefined»). */
export interface NotificationItem {
  id: string;
  kind: string;
  payload: Record<string, string>;
  created_at: string;
  read_at: string | null;
}

export interface NotificationsPage {
  items: NotificationItem[];
  /** По всей ленте, не по срезу — бейдж не должен обещать меньше, чем есть. */
  unread: number;
}

export async function getNotifications(): Promise<NotificationsPage> {
  const { data } = await api.get("/notifications");
  return data;
}

/** Погасить всё непрочитанное разом. Идемпотентно — повторный вызов ноль. */
export async function markNotificationsRead(): Promise<{ read: number }> {
  const { data } = await api.post("/notifications/read");
  return data;
}

export async function getMatches(signal?: AbortSignal): Promise<MatchResponse[]> {
  const { data } = await api.get("/matches");
  return data;
}

export async function likeProfile(
  targetId: string,
  type: "like" | "superlike" | "pass" = "like",
  /** Пара слов, которые получатель увидит ещё до мэтча. */
  message = ""
): Promise<{
  liked: boolean;
  matched: boolean;
  match?: MatchResponse;
}> {
  const { data } = await api.post("/likes", { target_id: targetId, type, message });
  return data;
}

/** Как просить страницу переписки: хвост, назад по времени или вокруг сообщения. */
export interface MessagesQuery {
  /**
   * Курсор прокрутки вверх — время самого старого загруженного сообщения.
   * Именно время, а не смещение: пришедшее за это время новое сообщение
   * сдвигает окно offset и одна и та же строка приезжает дважды.
   */
  before?: string;
  /** Страница вокруг сообщения — прыжок из витрины вложений и из цитаты. */
  around?: string;
  limit?: number;
}

export async function getMessages(
  matchId: string,
  query: MessagesQuery = {},
): Promise<ChatMessage[]> {
  const { data } = await api.get(`/matches/${matchId}/messages`, { params: query });
  return data;
}

/**
 * Поставить, сменить или снять реакцию. Тот же код второй раз — снятие,
 * это решает сервер: клиент не должен угадывать, что там сейчас лежит,
 * иначе два быстрых нажатия разъезжаются с базой.
 */
export async function putReaction(
  matchId: string,
  messageId: string,
  key: string | null,
): Promise<{ message_id: string; reactions: MessageReaction[] }> {
  const { data } = await api.put(
    `/matches/${matchId}/messages/${messageId}/reaction`,
    { key },
  );
  return data;
}

export async function uploadPhoto(file: File): Promise<{ url: string; key: string }> {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await api.post("/upload/photo", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

/**
 * Видеоролик анкеты. Контракт как у публикации ролика в ленте: сервер видео
 * не разбирает, кадры с разных таймкодов снимает браузер (grabVideoCovers),
 * и модерация смотрит на них — без кадров загрузки нет.
 * URL из ответа кладётся в анкету через PATCH /profiles/me (поле videos).
 */
export async function uploadProfileVideo(
  file: File,
  covers: Blob[]
): Promise<{ url: string; key: string }> {
  const form = new FormData();
  form.append("file", file);
  covers.forEach((cover, i) => form.append("covers", cover, `cover${i + 1}.jpg`));
  const { data } = await api.post("/upload/video", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

/**
 * Голосовое для лички. Файл ложится в R2 под папкой отправителя — доставка
 * принимает в сообщение только такие ссылки (чужую запись не переслать).
 * Длительность считает клиент, сервер сверяет диапазон 1–60 с.
 */
export async function uploadVoice(
  blob: Blob,
  duration: number
): Promise<{ url: string; key: string; duration: number }> {
  const form = new FormData();
  form.append("file", blob, `voice.${extFor(blob.type)}`);
  form.append("duration", String(Math.max(1, Math.round(duration))));
  const { data } = await api.post("/upload/voice", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

/**
 * Видеокружок для лички. Как у видео анкеты: сервер ролик не разбирает,
 * кадры с разных моментов записи снимает клиент — по ним модерация.
 */
export async function uploadVideoNote(
  blob: Blob,
  covers: Blob[],
  duration: number
): Promise<{ url: string; key: string; duration: number; poster?: string | null }> {
  const form = new FormData();
  form.append("file", blob, `note.${extFor(blob.type)}`);
  covers.forEach((cover, i) => form.append("covers", cover, `cover${i + 1}.jpg`));
  form.append("duration", String(Math.max(1, Math.round(duration))));
  const { data } = await api.post("/upload/video-note", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

function extFor(mime: string): string {
  const base = mime.split(";")[0];
  if (base.endsWith("/mp4")) return base.startsWith("audio") ? "m4a" : "mp4";
  if (base.endsWith("/ogg")) return "ogg";
  if (base.endsWith("/quicktime")) return "mov";
  if (base.endsWith("/mpeg")) return "mp3";
  return "webm";
}

export async function reportUser(reportedId: string, reason: string, description = ""): Promise<void> {
  await api.post("/report", { reported_id: reportedId, reason, description });
}

/** Заблокировать навсегда: в отличие от размэтча, пара больше не увидит
 *  друг друга в деке и не сможет связаться. */
export async function blockUser(targetId: string): Promise<void> {
  await api.post(`/blocks/${targetId}`);
}

export async function unblockUser(targetId: string): Promise<void> {
  await api.delete(`/blocks/${targetId}`);
}

export async function getBlockedUsers(): Promise<UserProfile[]> {
  const { data } = await api.get("/blocks");
  return data;
}

export async function authDev(deviceId: string, name = ""): Promise<{ token: string; user: UserProfile }> {
  const { data } = await api.post("/auth/dev", { device_id: deviceId, name });
  if (!data.success) throw new Error("Dev auth disabled");
  return { token: data.token, user: data.user };
}

export interface SuperlikeQuota {
  left: number;
  total: number;
  is_premium: boolean;
}

/** Остаток суперлайков на сутки — для счётчика на кнопке в деке. */
export async function getSuperlikeQuota(): Promise<SuperlikeQuota> {
  const { data } = await api.get("/likes/superlikes");
  return data;
}

export async function getLikesReceived(): Promise<UserProfile[]> {
  const { data } = await api.get("/likes/received");
  return data;
}

/** Суточные лимиты бесплатного уровня: лайки и открытия мэтчей.
 *  `-1` в `*_total` — без ограничения (подписка). `*_reset_at` — время, когда
 *  вернётся первый израсходованный слот: окно скользящее, а не «в полночь». */
export interface DailyLimits {
  likes_left: number;
  likes_total: number;
  likes_reset_at?: string | null;
  matches_left: number;
  matches_total: number;
  matches_reset_at?: string | null;
  is_premium: boolean;
}

/** Признак «ограничения нет» — тот же сентинел, что `UNLIMITED` на сервере.
 *  Ноль занят смыслом «нельзя совсем», поэтому безлимит отрицательный. */
export function безлимит(total: number): boolean {
  return total < 0;
}

/** Остатки суточных лимитов. Дека зовёт при открытии (счётчик), шторка
 *  лимита — после 429, чтобы показать точное время возврата вместо
 *  бессодержательного «попробуйте позже». */
export async function getDailyLimits(): Promise<DailyLimits> {
  const { data } = await api.get("/likes/limits");
  return data;
}

/* ── Личка без взаимного лайка («Мимолёт») ──────────────────── */

export interface DirectQuota {
  left: number;
  total: number;
  /** false — тариф вовсе не позволяет, а не только лимит на сегодня. */
  allowed: boolean;
  /** Имя уровня, с которого фича открывается. Приходит с сервера, чтобы
      название тарифа не было зашито в двух местах сразу. */
  required_tier_name: string;
}

/** Остаток писем без взаимного лайка — для честного гейта на кнопке. */
export async function getDirectQuota(): Promise<DirectQuota> {
  const { data } = await api.get("/matches/direct/quota");
  return data;
}

/** Написать человеку, который вас не лайкал — платный крючок. Заводит
 *  переписку kind="direct" и сразу отправляет первое сообщение. */
export async function sendDirectMessage(
  targetId: string,
  text: string
): Promise<MatchResponse> {
  const { data } = await api.post("/matches/direct", { target_id: targetId, text });
  return data.match;
}

export async function unmatch(matchId: string): Promise<void> {
  await api.post(`/matches/${matchId}/unmatch`);
}

export async function getIcebreakers(matchId: string): Promise<string[]> {
  const { data } = await api.get(`/matches/${matchId}/icebreakers`);
  return data.icebreakers ?? [];
}

/** Одно вложение переписки. Форма одна на все пять видов — см. API. */
export interface ChatAttachment {
  /** По нему витрина прыгает к сообщению, а не открывает файл в отрыве. */
  message_id: string;
  kind: "photo" | "reel" | "video_note" | "voice" | "link";
  url: string;
  /** Кадр кружка или обложка ролика; у фото совпадает с url. */
  poster: string;
  /** Фигура кружка (circle, heart, star…) — витрина рисует ту же. */
  shape: string;
  duration: number | null;
  waveform: string;
  /** Домен ссылки — заголовок строки. */
  host: string;
  from_me: boolean;
  created_at: string | null;
}

/** Что переслали друг другу за переписку: счётчики по всей, списки — страницей. */
export interface ChatAttachments {
  photos: number;
  reels: number;
  video_notes: number;
  voices: number;
  voice_seconds: number;
  links: number;
  media: ChatAttachment[];
  voice: ChatAttachment[];
  link: ChatAttachment[];
}

export async function getChatAttachments(matchId: string): Promise<ChatAttachments> {
  const { data } = await api.get(`/matches/${matchId}/attachments`);
  return data;
}

/**
 * Полное удаление аккаунта и всех связанных данных.
 * Обязательная возможность по требованиям App Store (Guideline 5.1.1(v)).
 */
export async function deleteMyAccount(): Promise<void> {
  await api.delete("/profiles/me");
}

/** Экспорт своих данных — ожидаемая возможность для приватности. */
export async function exportMyData(): Promise<Blob> {
  const { data } = await api.get("/profiles/me/export", { responseType: "blob" });
  return data;
}

/* ── Видео-лента (reels) ────────────────────────────────────── */

export interface Reel {
  id: string;
  author_id: string;
  author_name: string;
  author_age?: number | null;
  author_photo: string;
  video_url: string;
  cover_url: string;
  caption: string;
  likes_count: number;
  comments_count: number;
  views_count: number;
  liked_by_me: boolean;
  is_mine: boolean;
  /** Снят с показа модерацией — приходит только автору. */
  is_hidden: boolean;
  created_at?: string | null;
}

export interface ReelComment {
  id: string;
  author_id: string;
  author_name: string;
  author_photo: string;
  text: string;
  is_mine: boolean;
  created_at?: string | null;
}

export interface ReelsPage {
  reels: Reel[];
  next_before?: string | null;
}

export async function getReels(before?: string | null): Promise<ReelsPage> {
  const { data } = await api.get("/reels", {
    params: before ? { before } : undefined,
  });
  return data;
}

export async function getMyReels(): Promise<ReelsPage> {
  const { data } = await api.get("/reels/mine");
  return data;
}

/**
 * Публикация ролика. Кадры присылаем отдельными файлами: сервер не разбирает
 * видео сам, и модерация идёт по этим кадрам — без них публикации нет. Кадров
 * несколько и по возрастанию времени: по одному нельзя поручиться за весь
 * ролик, а средний сервер сохраняет обложкой.
 */
export async function uploadReel(
  video: File,
  covers: Blob[],
  caption: string
): Promise<Reel> {
  const form = new FormData();
  form.append("video", video);
  covers.forEach((cover, i) => form.append("covers", cover, `cover${i + 1}.jpg`));
  form.append("caption", caption);
  const { data } = await api.post("/reels", form);
  return data;
}

export async function toggleReelLike(reelId: string): Promise<Reel> {
  const { data } = await api.post(`/reels/${reelId}/like`);
  return data;
}

export async function deleteReel(reelId: string): Promise<void> {
  await api.delete(`/reels/${reelId}`);
}

/**
 * Переслать ролик в личный чат мэтча или в комнату. Наружу не шарим: ссылку
 * всё равно откроют внутри Telegram, а вне него она бесполезна.
 */
export async function forwardReel(
  reelId: string,
  target: { matchId?: string; roomId?: string },
  text = ""
): Promise<void> {
  await api.post(`/reels/${reelId}/forward`, {
    // Сервер ждёт одно из двух полей; лишний null он бы принял, но пустое
    // тело читается однозначнее в логах
    ...(target.matchId ? { match_id: target.matchId } : {}),
    ...(target.roomId ? { room_id: target.roomId } : {}),
    text,
  });
}

export async function getReelComments(reelId: string): Promise<ReelComment[]> {
  const { data } = await api.get(`/reels/${reelId}/comments`);
  return data.comments;
}

export async function addReelComment(
  reelId: string,
  text: string
): Promise<ReelComment> {
  const { data } = await api.post(`/reels/${reelId}/comments`, { text });
  return data;
}

export async function deleteReelComment(
  reelId: string,
  commentId: string
): Promise<void> {
  await api.delete(`/reels/${reelId}/comments/${commentId}`);
}

export async function reportReel(
  reelId: string,
  reason: string,
  description = ""
): Promise<void> {
  await api.post(`/reels/${reelId}/report`, { reason, description });
}

/** Жалоба на комментарий: у зрителя должна быть не только кнопка автора
    «удалить», иначе грубость висит, пока владелец ролика не зайдёт. */
export async function reportReelComment(
  reelId: string,
  commentId: string,
  reason: string
): Promise<void> {
  await api.post(`/reels/${reelId}/comments/${commentId}/report`, {
    reason,
    description: "",
  });
}

export async function reportStory(storyId: string, reason: string): Promise<void> {
  await api.post(`/stories/${storyId}/report`, { reason, description: "" });
}

export async function reportRoomMessage(
  roomId: string,
  messageId: string,
  reason: string
): Promise<void> {
  await api.post(`/rooms/${roomId}/messages/${messageId}/report`, {
    reason,
    description: "",
  });
}

/** Просмотр: ошибку глушим, статистика не должна мешать смотреть. */
export async function recordReelView(reelId: string): Promise<void> {
  try {
    await api.post(`/reels/${reelId}/view`);
  } catch {
    /* не мешаем просмотру */
  }
}

/* ── Учёт открытий разделов ─────────────────────────────────── */

/** Коды разделов. Должны совпадать с KNOWN_SECTIONS в api/routers/sections.py. */
export type Section =
  | "reels"
  | "rooms"
  | "voice"
  | "photo_ratings"
  | "cases"
  | "leaderboard"
  | "daily"
  | "tarot"
  | "habits"
  | "chat_theme"
  | "appearance"
  | "stories";

/**
 * Отметить открытие раздела.
 *
 * Ошибку глушим: аналитика не должна ломать экран, который она измеряет.
 * Разделов много, и без этих цифр спор «что лишнее» решается вкусом, а не
 * данными.
 */
export async function recordSectionOpen(section: Section): Promise<void> {
  try {
    await api.post(`/sections/${section}/open`);
  } catch {
    /* не мешаем работе экрана */
  }
}

/* ── Голосовая рулетка ──────────────────────────────────────── */

/** Параметры WebRTC приходят с сервера: TURN-креденшелы меняются. */
export async function getIceServers(): Promise<RTCIceServer[]> {
  const { data } = await api.get("/voice/ice-servers");
  return data.ice_servers;
}

/* ── Карта дня ──────────────────────────────────────────────── */

export interface DailyCard {
  name: string;
  meaning: string;
  advice: string;
}

export async function getDailyCard(): Promise<DailyCard> {
  const { data } = await api.get("/daily/card");
  return data;
}

/* ── Таро ───────────────────────────────────────────────────── */

export type TarotSpreadType = "day" | "pair" | "three" | "relationship";

export interface TarotCard {
  position: string;
  name: string;
  meaning: string;
}

export interface TarotSpread {
  spread: TarotSpreadType;
  title: string;
  cards: TarotCard[];
  interpretation: string;
  disclaimer: string;
  /** Открыты ли развороты на текущем тарифе. Едет с картой дня, чтобы клиент
      не выяснял это отдельным запросом к закрытому раскладу. */
  spreads_open?: boolean;
  /** Уровень, с которого открываются развороты. */
  required_tier_name?: string;
}

export async function getTarotDay(): Promise<TarotSpread> {
  const { data } = await api.get("/tarot/day");
  return data;
}

export async function getTarotThree(): Promise<TarotSpread> {
  const { data } = await api.get("/tarot/three");
  return data;
}

export async function getTarotRelationship(): Promise<TarotSpread> {
  const { data } = await api.get("/tarot/relationship");
  return data;
}

export async function getTarotPair(nameA: string, nameB: string): Promise<TarotSpread> {
  const { data } = await api.get("/tarot/pair", {
    params: { name_a: nameA, name_b: nameB },
  });
  return data;
}

/* ── Кейсы ──────────────────────────────────────────────────── */

/** Коллекционная наклейка. `image` приходит с сервера — путь там же, где данные. */
export interface Sticker {
  code: string;
  title: string;
  rarity: string;
  rarity_title: string;
  image: string;
  /** Код набора — он же код кейса, из которого наклейка выпадает. */
  set: string;
  /** Сколько раз выпала. 0 — ещё нет в коллекции. */
  owned: number;
}

/** Набор наклеек в коллекции: заголовок группы и прогресс по ней. */
export interface StickerSet {
  code: string;
  title: string;
  owned: number;
  total: number;
}

/** Кейс на витрине: набор, прогресс и картинки-приманки. */
export interface CaseDef {
  code: string;
  title: string;
  hint: string;
  /** Цвет свечения плитки — с сервера, чтобы новый кейс не требовал клиента. */
  accent: string;
  total: number;
  owned: number;
  preview: string[];
  /** Доли редкостей внутри набора, процентами. */
  rarity_chances: Record<string, number>;
}

export interface CaseReward {
  code: string;
  title: string;
  amount: number;
  chance_percent: number;
  /** Заполнено, только если выпала наклейка. */
  sticker?: Sticker | null;
  /** Заполнено, только если выпала обложка карточки. */
  decor?: DecorItem | null;
}

export interface StickerCollection {
  stickers: Sticker[];
  /** Наборы в порядке витрины — коллекция группируется по ним. */
  sets: StickerSet[];
  owned: number;
  total: number;
  /** Выбранная — её видят другие в анкете. */
  selected?: string | null;
}

export interface CaseState {
  left: number;
  per_month: number;
  /** Когда квота обновится — первое число следующего месяца (UTC). */
  resets_at?: string | null;
  /** Типы наград и их шансы — одинаковы для всех кейсов. */
  rewards: CaseReward[];
  /** Кейсы в порядке витрины. */
  cases: CaseDef[];
  /** Уровень, с которого кейсы открываются, — с сервера, не словом в клиенте. */
  required_tier_name: string;
}

export interface CaseOpenResult {
  reward: CaseReward;
  /** Код открытого кейса. */
  case: string;
  left: number;
  per_month: number;
  resets_at?: string | null;
  /** Повтор наклейки. Возможен только у полностью собранной коллекции. */
  duplicate?: boolean;
}

export async function getStickers(): Promise<StickerCollection> {
  const { data } = await api.get("/cases/stickers");
  return data;
}

/** Пустой код снимает выбор. */
export async function selectSticker(code: string): Promise<StickerCollection> {
  const { data } = await api.post("/cases/stickers/select", { code });
  return data;
}

export async function getCaseState(): Promise<CaseState> {
  const { data } = await api.get("/cases");
  return data;
}

/** Открыть кейс по коду: наборы разные, «какой-нибудь» нет. */
export async function openCase(caseCode: string): Promise<CaseOpenResult> {
  const { data } = await api.post("/cases/open", { case: caseCode });
  return data;
}

/* ── Групповые чаты ─────────────────────────────────────────── */

export interface Room {
  id: string;
  slug: string;
  title: string;
  description: string;
  city: string;
  /** Сообщений за сутки — по нему видно, где сейчас живо. */
  messages_today: number;
}

export interface RoomMessage {
  id: string;
  sender_id: string;
  sender_name: string;
  sender_photo: string;
  text: string;
  reel?: ReelPreview | null;
  is_mine: boolean;
  created_at?: string | null;
}

export async function getRooms(signal?: AbortSignal): Promise<Room[]> {
  const { data } = await api.get("/rooms", { signal });
  return data.rooms;
}

export async function getRoomMessages(
  roomId: string,
  before?: string | null
): Promise<{ messages: RoomMessage[]; next_before?: string | null }> {
  const { data } = await api.get(`/rooms/${roomId}/messages`, {
    params: before ? { before } : undefined,
  });
  return data;
}

export async function sendRoomMessage(
  roomId: string,
  text: string
): Promise<RoomMessage> {
  const { data } = await api.post(`/rooms/${roomId}/messages`, { text });
  return data;
}

/* ── Оценка фото ────────────────────────────────────────────── */

export interface PhotoRatingTarget {
  user_id: string;
  display_name: string;
  photo: string;
}

export interface MyPhotoRating {
  photo: string;
  /** null — оценок ещё нет. */
  average?: number | null;
  total: number;
  /** Видимые оценки: кто и сколько поставил (свежие первыми). */
  feed: RatingFeedItem[];
}

export interface RatingFeedItem {
  user_id: string;
  display_name: string;
  photo: string;
  age?: number | null;
  city: string;
  score: number;
  updated_at?: string | null;
}

export async function getRatingQueue(): Promise<PhotoRatingTarget[]> {
  const { data } = await api.get("/photo-ratings/queue");
  return data.targets;
}

export async function ratePhoto(targetId: string, score: number): Promise<void> {
  await api.post("/photo-ratings", { target_id: targetId, score });
}

export async function getMyPhotoRating(): Promise<MyPhotoRating> {
  const { data } = await api.get("/photo-ratings/mine");
  return data;
}

/* ── Топ по лайкам ──────────────────────────────────────────── */

export interface LeaderboardEntry {
  place: number;
  user_id: string;
  display_name: string;
  photo: string;
  likes: number;
  is_me: boolean;
}

export interface LeaderboardOut {
  window_days: number;
  /** Какой период реально посчитан: "today" | "week". */
  period: string;
  entries: LeaderboardEntry[];
  my_place?: number | null;
  my_likes: number;
  /** false — человек вне посчитанных мест, точный номер неизвестен. */
  my_place_exact: boolean;
}

export async function getLeaderboard(period: "today" | "week" = "week"): Promise<LeaderboardOut> {
  const { data } = await api.get("/leaderboard", { params: { period } });
  return data;
}

/* ── Буст показов ───────────────────────────────────────────── */

export interface BoostState {
  active: boolean;
  until?: string | null;
  minutes: number;
  /** Суточные включения плюс купленные паком. */
  left_today: number;
  per_day: number;
  /** Сколько из left_today куплено за Stars — не возобновляются. */
  bonus: number;
  /** Уровень, который открывает буст — приходит с сервера, чтобы не писать
   *  имя тарифа словом: гейт живёт в FEATURE_MIN_TIER. */
  required_tier_name: string;
}

export async function getBoost(): Promise<BoostState> {
  const { data } = await api.get("/profiles/me/boost");
  return data;
}

export async function activateBoost(): Promise<BoostState> {
  const { data } = await api.post("/profiles/me/boost");
  return data;
}

/* ── Гости ──────────────────────────────────────────────────── */

export interface VisitorOut {
  profile: UserProfile;
  visits: number;
  last_seen_at?: string | null;
}

export interface VisitorsOut {
  total: number;
  /** false — число гостей известно, а кто именно, видно только на Ultra. */
  revealed: boolean;
  visitors: VisitorOut[];
  period: "today" | "week" | "all";
}

export async function getMyVisitors(
  period: "today" | "week" | "all" = "all"
): Promise<VisitorsOut> {
  const { data } = await api.get("/profiles/me/visitors", { params: { period } });
  return data;
}

/**
 * Отметить, что анкета показана. Ошибку глушим: статистика визитов не должна
 * мешать свайпать, а повтор всё равно только обновит время.
 */
export async function recordVisit(profileId: string): Promise<void> {
  try {
    await api.post(`/profiles/${profileId}/visit`);
  } catch {
    /* не мешаем просмотру */
  }
}

/* ── Тарифы ─────────────────────────────────────────────────── */

export interface PlanOut {
  code: string;
  tier: string;
  title: string;
  months: number;
  price_rub: number;
  price_per_month: number;
  /** Цена за день — ею продаётся длинный срок. */
  price_per_day: number;
  appstore_id: string;
}

export interface TierOut {
  tier: string;
  name: string;
  superlikes: number;
  perks: string[];
  plans: PlanOut[];
}

export interface PlansOut {
  current_tier: string;
  tiers: TierOut[];
}

/** Транзакция и подтверждённая подписка. `gift_code` выдаётся только при
 *  продаже подарка — иначе его бы видно в логе. */
export interface IAPVerifyResponse {
  success: boolean;
  plan: string;
  expires_at: string;
  already_processed: boolean;
  gift_code?: string | null;
}

/**
 * Витрина тарифов. Цены приходят с сервера, а не хранятся в клиенте: иначе
 * бот и мини-апп разошлись бы в ценнике после первой же правки.
 */
export async function getPlans(): Promise<PlansOut> {
  const { data } = await api.get("/iap/plans");
  return data;
}

/** Что дала активация промокода. plan/expires_at — итоговая подписка:
 *  если уровень человека уже выше, plan останется прежним, а срок вырастет. */
export interface PromoActivateOut {
  tier: string;
  days: number;
  plan: string;
  expires_at: string;
}

/** Активировать промокод. Регистр, пробелы и дефисы нормализует сервер.
 *  Отказы приходят статусами: 404 нет такого, 409 уже активировал,
 *  410 истёк или закончился — текст для человека лежит в detail. */
export async function activatePromo(code: string): Promise<PromoActivateOut> {
  const { data } = await api.post("/promo/activate", { code });
  return data;
}

/** Что дала активация подарочного кода: tier/months — что лежало в коробке,
 *  plan/expires_at — итоговая подписка (равный уровень продлевается поверх
 *  остатка). */
export interface GiftRedeemOut {
  tier: string;
  months: number;
  plan: string;
  expires_at: string;
}

/** Активировать подарочный код. Нормализация ввода — на сервере, как у
 *  промокодов. Отказы статусами: 404 нет такого, 402 не оплачен, 409 уже
 *  активирован ИЛИ уровень уже выше (код при этом цел), 410 истёк —
 *  текст для человека лежит в detail. */
export async function redeemGift(code: string): Promise<GiftRedeemOut> {
  const { data } = await api.post("/gifts/redeem", { code });
  return data;
}

/** Регистрация устройства для пуш-уведомлений в нативной обёртке. */
export async function registerDevice(token: string, platform: string): Promise<void> {
  await api.post("/profiles/me/devices", { token, platform });
}

/** Выход: гасит токен на сервере, иначе он остаётся годным до конца срока.
 *
 * Ошибку намеренно проглатываем — локальный выход должен состояться даже
 * при недоступном бэкенде, иначе на чужом устройстве не выйти вообще.
 */
export async function logoutServerSide(): Promise<void> {
  try {
    await api.post("/auth/logout");
  } catch {
    // токен истечёт сам; локальные данные всё равно чистятся
  }
}

/**
 * Выход со ВСЕХ устройств: гасит все выданные токены, включая текущий.
 * Нужен, когда доступ мог попасть к чужому — обычный выход чужую сессию
 * не трогает, и она живёт до истечения токена (до 72 часов).
 */
export async function logoutEverywhere(): Promise<void> {
  await api.post("/auth/logout-all");
}

/** Восстановить прогаревшую серию общения — после одного дня тишины.
 * Серия платная: лимит на пару в месяц зависит от её длины (1/2/3). */
export async function reviveStreak(matchId: string): Promise<{
  success: boolean;
  streak_days: number;
  streak_emoji: string;
  streak_revives_left: number;
}> {
  const { data } = await api.post(`/matches/${matchId}/revive-streak`);
  return data;
}

// ════════════════════════════════════════════════════════════════
//  ТЕМА ЧАТА
// ════════════════════════════════════════════════════════════════

export interface ChatTheme {
  match_id: string;
  bubble_mine_color: string | null;
  bubble_theirs_color: string | null;
  background_color: string | null;
  pattern_key: string | null;
}

export interface ChatThemePreset {
  key: string;
  name: string;
  bubble_mine_color: string;
  bubble_theirs_color: string;
  background_color: string;
  pattern_key: string;
  min_tier: string;
  locked: boolean;
}

export interface ChatThemePresets {
  presets: ChatThemePreset[];
  tier: string;
  custom_allowed: boolean;
}

export async function getChatThemePresets(): Promise<ChatThemePresets> {
  const { data } = await api.get("/chat-themes/presets");
  return data;
}

export async function getChatTheme(matchId: string): Promise<ChatTheme> {
  const { data } = await api.get(`/chat-themes/${matchId}`);
  return data;
}

export async function setChatTheme(
  matchId: string,
  body:
    | { preset: string }
    | {
        bubble_mine_color?: string | null;
        bubble_theirs_color?: string | null;
        background_color?: string | null;
        pattern_key?: string | null;
      },
): Promise<ChatTheme> {
  const { data } = await api.put(`/chat-themes/${matchId}`, body);
  return data;
}

export async function resetChatTheme(matchId: string): Promise<ChatTheme> {
  const { data } = await api.delete(`/chat-themes/${matchId}`);
  return data;
}

// ════════════════════════════════════════════════════════════════
//  ЗАДАЧИ ДНЯ
// ════════════════════════════════════════════════════════════════

export interface Habit {
  id: string;
  name: string;
  target_per_day: number;
  today_count: number;
  done_today: boolean;
}

export interface HabitsResponse {
  habits: Habit[];
  limit: number;
}

export async function getHabits(): Promise<HabitsResponse> {
  const { data } = await api.get("/habits");
  return data;
}

export async function createHabit(
  name: string,
  target_per_day = 1,
): Promise<Habit> {
  const { data } = await api.post("/habits", { name, target_per_day });
  return data;
}

export async function checkHabit(habitId: string): Promise<Habit> {
  const { data } = await api.post(`/habits/${habitId}/check`);
  return data;
}

export async function uncheckHabit(habitId: string): Promise<Habit> {
  const { data } = await api.post(`/habits/${habitId}/uncheck`);
  return data;
}

export async function deleteHabit(habitId: string): Promise<void> {
  await api.delete(`/habits/${habitId}`);
}

// ════════════════════════════════════════════════════════════════
//  ИСТОРИИ
// ════════════════════════════════════════════════════════════════

export interface Story {
  id: string;
  user_id: string;
  display_name: string;
  media_url: string;
  caption: string;
  audience: "matches" | "everyone";
  created_at: string;
  expires_at: string;
  views_count: number | null;
  seen: boolean;
  mine: boolean;
}

export interface StoryAuthor {
  user_id: string;
  display_name: string;
  avatar: string | null;
  count: number;
  latest_at: string;
  has_unseen: boolean;
}

export interface StoriesFeed {
  authors: StoryAuthor[];
  mine: Story[];
}

export interface StoryViewer {
  user_id: string;
  display_name: string;
  avatar: string | null;
  viewed_at: string;
}

export async function getStoriesFeed(): Promise<StoriesFeed> {
  const { data } = await api.get("/stories/feed");
  return data;
}

export async function getUserStories(userId: string): Promise<Story[]> {
  const { data } = await api.get(`/stories/user/${userId}`);
  return data;
}

export async function publishStory(
  file: File,
  caption: string,
  audience: "matches" | "everyone",
): Promise<Story> {
  const form = new FormData();
  form.append("file", file);
  form.append("caption", caption);
  form.append("audience", audience);
  // Загрузка кадра дольше обычного запроса: таймаут инстанса 15 секунд
  // отменил бы её на медленной сети уже после отправки половины файла.
  const { data } = await api.post("/stories", form, { timeout: 60000 });
  return data;
}

export async function markStoryViewed(storyId: string): Promise<void> {
  await api.post(`/stories/${storyId}/view`);
}

export async function getStoryViewers(
  storyId: string,
): Promise<{ viewers: StoryViewer[]; total: number }> {
  const { data } = await api.get(`/stories/${storyId}/viewers`);
  return data;
}

export async function getStoryReplyTarget(
  storyId: string,
): Promise<{ match_id: string; prefill: string }> {
  const { data } = await api.post(`/stories/${storyId}/reply`);
  return data;
}

export async function deleteStory(storyId: string): Promise<void> {
  await api.delete(`/stories/${storyId}`);
}

export interface DecorItem {
  code: string;
  title: string;
  rarity: string;
  rarity_title: string;
  /** Есть ли обложка в коллекции. Носить можно только свою. */
  unlocked: boolean;
}

export interface DecorCollection {
  decors: DecorItem[];
  selected?: string | null;
  owned: number;
  total: number;
}

export async function getDecor(): Promise<DecorCollection> {
  const { data } = await api.get("/cases/decor");
  return data;
}

/** Надеть рамку. Пустой код снимает. Право проверяет сервер. */
export async function selectDecor(code: string): Promise<DecorCollection> {
  const { data } = await api.post("/cases/decor/select", { code });
  return data;
}
