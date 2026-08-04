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

// Auto-logout on 401
api.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("sd_token");
      localStorage.removeItem("sd_user");
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
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
  display_name: string;
  bio: string;
  gender: string;
  age?: number | null;
  city: string;
  photos: string[];
  interests: string[];
  ai_bio?: string | null;
  looking_for: string;
  is_incognito: boolean;
  hide_age?: boolean;
  hide_distance?: boolean;
  hide_from_visitors?: boolean;
  is_premium?: boolean;
  age_min?: number;
  age_max?: number;
  distance_max?: number;
  // Нишевые поля анкеты и фильтры по ним: пусто — не указано / не фильтруем
  goal?: string;
  subculture?: string;
  mbti?: string;
  height_cm?: number | null;
  filter_goal?: string;
  filter_subculture?: string;
  filter_city?: string;
  filter_height_min?: number | null;
  filter_height_max?: number | null;
  /** Только в списке «кто меня лайкнул»: текст, приложенный к лайку. */
  like_message?: string;
  /** Карточка скрыта до подписки: имени и фото в ответе нет. */
  is_locked?: boolean;
  has_location?: boolean;
  invited_count?: number;
  referral_boost?: boolean;
  referral_target?: number;
  referral_boost_percent?: number;
}

export interface DeckProfile {
  id: string;
  display_name: string;
  age?: number | null;
  city: string;
  bio: string;
  photos: string[];
  interests: string[];
  ai_bio?: string | null;
  distance?: number | null;
  match_score?: number | null;
  match_reason?: string | null;
  goal?: string;
  subculture?: string;
  mbti?: string;
  height_cm?: number | null;
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
}

export interface ChatMessage {
  id: string;
  sender_id: string;
  text: string;
  image_url?: string | null;
  read_at?: string | null;
  created_at?: string | null;
}

// ── API Functions ──────────────────────────────────────────────

export async function authWithTelegram(initData: string): Promise<{ token: string; user: UserProfile }> {
  const { data } = await api.post("/auth/telegram", { initData });
  return { token: data.token, user: data.user };
}

/** Вход по одноразовому коду из бота (команда /link) — путь для iOS-приложения,
 *  где Telegram initData недоступен. */
export async function authWithLinkCode(code: string): Promise<{ token: string; user: UserProfile }> {
  const { data } = await api.post("/auth/link", { code });
  if (!data.success) throw new Error("Неверный или устаревший код");
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

export async function getMatches(): Promise<MatchResponse[]> {
  const { data } = await api.get("/matches");
  return data;
}

export async function getMessages(matchId: string): Promise<ChatMessage[]> {
  const { data } = await api.get(`/matches/${matchId}/messages`);
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

export async function unmatch(matchId: string): Promise<void> {
  await api.post(`/matches/${matchId}/unmatch`);
}

export async function getIcebreakers(matchId: string): Promise<string[]> {
  const { data } = await api.get(`/matches/${matchId}/icebreakers`);
  return data.icebreakers ?? [];
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
  liked_by_me: boolean;
  is_mine: boolean;
  /** Снят с показа модерацией — приходит только автору. */
  is_hidden: boolean;
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
 * Публикация ролика. Обложку присылаем отдельным файлом: сервер не разбирает
 * видео на кадры, и модерация идёт по этому кадру — без него публикации нет.
 */
export async function uploadReel(
  video: File,
  cover: Blob,
  caption: string
): Promise<Reel> {
  const form = new FormData();
  form.append("video", video);
  form.append("cover", cover, "cover.jpg");
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

/* ── Кейсы ──────────────────────────────────────────────────── */

export interface CaseReward {
  code: string;
  title: string;
  amount: number;
  chance_percent: number;
}

export interface CaseState {
  left_today: number;
  per_day: number;
  rewards: CaseReward[];
}

export interface CaseOpenResult {
  reward: CaseReward;
  left_today: number;
  per_day: number;
  boost_minutes: number;
}

export async function getCaseState(): Promise<CaseState> {
  const { data } = await api.get("/cases");
  return data;
}

export async function openCase(): Promise<CaseOpenResult> {
  const { data } = await api.post("/cases/open");
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
  is_mine: boolean;
  created_at?: string | null;
}

export async function getRooms(): Promise<Room[]> {
  const { data } = await api.get("/rooms");
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
  entries: LeaderboardEntry[];
  my_place?: number | null;
  my_likes: number;
  /** false — человек вне посчитанных мест, точный номер неизвестен. */
  my_place_exact: boolean;
}

export async function getLeaderboard(): Promise<LeaderboardOut> {
  const { data } = await api.get("/leaderboard");
  return data;
}

/* ── Буст показов ───────────────────────────────────────────── */

export interface BoostState {
  active: boolean;
  until?: string | null;
  minutes: number;
  left_today: number;
  per_day: number;
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
}

export async function getMyVisitors(): Promise<VisitorsOut> {
  const { data } = await api.get("/profiles/me/visitors");
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

/**
 * Витрина тарифов. Цены приходят с сервера, а не хранятся в клиенте: иначе
 * бот и мини-апп разошлись бы в ценнике после первой же правки.
 */
export async function getPlans(): Promise<PlansOut> {
  const { data } = await api.get("/iap/plans");
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
