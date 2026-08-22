import api from "./api";

// ── Admin Types ────────────────────────────────────────────────

export interface AdminStats {
  total_users: number;
  active_today: number;
  total_matches: number;
  total_likes: number;
  total_reports: number;
  pending_reports: number;
  premium_users: number;
  banned_users: number;
  new_users_week: number;
  new_users_month: number;
  registrations_chart: { date: string; count: number }[];
}

export interface AdminUser {
  id: string;
  telegram_id: number | null;
  display_name: string;
  gender: string;
  age: number | null;
  city: string;
  role: string;
  is_banned: boolean;
  is_verified: boolean;
  created_at: string | null;
}

/* ── Карточка пользователя ──────────────────────────────────── */

export interface AdminStrikeBlock {
  count: number;
  limit: number;
  window_days: number;
}

export interface AdminVerification {
  status: string;
  provider: string;
  reason: string;
  decided_at: string | null;
}

/** Досье одного пользователя: всё, что нужно разбору тикета, одним экраном. */
export interface AdminUserCard {
  id: string;
  telegram_id: number | null;
  role: string;
  locale: string;
  is_banned: boolean;
  banned_until: string | null;
  is_verified: boolean;
  created_at: string | null;
  last_seen_at: string | null;
  has_apple: boolean;
  has_email: boolean;
  display_name: string;
  gender: string;
  age: number | null;
  city: string;
  bio: string;
  photos: string[];
  interests: string[];
  is_incognito: boolean;
  is_paused: boolean;
  plan: string;
  plan_expires_at: string | null;
  matches_count: number;
  likes_sent: number;
  likes_received: number;
  reels_count: number;
  stories_count: number;
  strikes: Record<string, AdminStrikeBlock>;
  prior_bans: number;
  reports_against: number;
  reports_pending: number;
  reports_by: number;
  last_verification: AdminVerification | null;
  recent_moderation: AdminModerationLog[];
}

export interface AdminReport {
  id: string;
  reporter_id: string;
  reporter_name: string;
  reported_id: string;
  reported_name: string;
  reason: string;
  description: string;
  status: string;
  created_at: string | null;
}

export interface AdminModerationLog {
  id: string;
  user_id: string;
  user_name: string;
  content_type: string;
  content_preview: string;
  result: string;
  action: string;
  reason: string;
  created_at: string | null;
}

// ── Admin API ──────────────────────────────────────────────────

export async function getAdminStats(): Promise<AdminStats> {
  const { data } = await api.get("/admin/stats");
  return data;
}

export async function getAdminUsers(
  page = 1,
  limit = 50,
  search = "",
  bannedOnly = false
): Promise<AdminUser[]> {
  const { data } = await api.get("/admin/users", {
    params: { page, limit, search, banned_only: bannedOnly },
  });
  return data;
}

export async function getAdminUserCard(userId: string): Promise<AdminUserCard> {
  const { data } = await api.get(`/admin/users/${userId}`);
  return data;
}

/** durationHours=null — вечный бан (прежнее поведение кнопки «Забанить»). */
export async function banUser(
  userId: string,
  reason = "",
  durationHours: number | null = null
): Promise<void> {
  await api.post("/admin/users/ban", {
    user_id: userId,
    reason,
    duration_hours: durationHours,
  });
}

export async function unbanUser(userId: string): Promise<void> {
  await api.post("/admin/users/unban", { user_id: userId });
}

/** Ручное управление галочкой — для разборов поддержки: снять с того, кто
 *  сменил фото после проверки, или выдать тому, кого AI стабильно не узнаёт. */
export async function setUserVerified(userId: string, verified: boolean): Promise<void> {
  await api.post("/admin/users/set-verified", { user_id: userId, verified });
}

export async function getAdminReports(
  status = "pending",
  page = 1,
  limit = 50
): Promise<AdminReport[]> {
  const { data } = await api.get("/admin/reports", {
    params: { status, page, limit },
  });
  return data;
}

export async function resolveReport(
  reportId: string,
  action: "dismiss" | "resolve" | "ban_reported",
  note = ""
): Promise<void> {
  await api.post("/admin/reports/action", { report_id: reportId, action, note });
}

/* ── Очередь верификации ────────────────────────────────────── */

/** Застрявший в живой проверке: отказы есть, галочки нет. Кадры проверки —
 *  биометрия и не хранятся, поэтому админ решает по фото анкеты и причинам
 *  отказов AI (кнопкой «Выдать галочку» — та же ручка set-verified). */
export interface AdminVerificationQueueItem {
  user_id: string;
  display_name: string;
  photos: string[];
  age: number | null;
  city: string;
  attempts_total: number;
  rejected_total: number;
  rejected_24h: number;
  /** Суточный потолок отказов — по нему видно, упёрся ли человек в лимит. */
  daily_limit: number;
  last_status: string;
  last_reason: string;
  last_provider: string;
  last_attempt_at: string | null;
}

export async function getVerificationQueue(
  days = 14,
  page = 1,
  limit = 50
): Promise<AdminVerificationQueueItem[]> {
  const { data } = await api.get("/admin/verification-queue", {
    params: { days, page, limit },
  });
  return data;
}

/* ── Аудит действий админов ─────────────────────────────────── */

/** Запись «кто, что, с кем сделал в админке». Журнал append-only:
 *  переживает удаление и админа, и цели (имена — снапшоты). */
export interface AdminAuditEntry {
  id: string;
  admin_id: string;
  admin_name: string;
  action: string;
  target_user_id: string;
  target_name: string;
  details: Record<string, unknown>;
  created_at: string | null;
}

export async function getAdminAudit(
  action = "all",
  page = 1,
  limit = 50
): Promise<AdminAuditEntry[]> {
  const { data } = await api.get("/admin/audit", {
    params: { action, page, limit },
  });
  return data;
}

export async function getModerationLogs(
  resultFilter = "all",
  page = 1,
  limit = 50
): Promise<AdminModerationLog[]> {
  const { data } = await api.get("/admin/moderation-logs", {
    params: { result_filter: resultFilter, page, limit },
  });
  return data;
}

/* ── Сводка по разделам ─────────────────────────────────────── */

export interface SectionStat {
  section: string;
  users: number;
  opens: number;
  /** Какая доля людей вообще заходила в раздел. */
  reach_percent: number;
}

export interface SectionStats {
  days: number;
  total_users: number;
  sections: SectionStat[];
}

/**
 * По этой сводке решают, какие разделы оставить. Живёт не в /admin, а в
 * /sections: запись открытия делает обычный пользователь, и держать половину
 * ручки в админском роутере значило бы разнести одну фичу по двум местам.
 */
export async function getSectionStats(days = 30): Promise<SectionStats> {
  const { data } = await api.get("/sections/stats", { params: { days } });
  return data;
}

/**
 * Ролик в очереди модерации.
 *
 * AI смотрит только присланные кадры, поэтому ручной просмотр нужен: то, что
 * начинается прилично, дальше может быть любым.
 */
export interface AdminReel {
  id: string;
  author_id: string;
  author_name: string;
  video_url: string;
  cover_url: string;
  caption: string;
  likes_count: number;
  is_hidden: boolean;
  created_at?: string | null;
}

export async function getAdminReels(onlyVisible = false): Promise<AdminReel[]> {
  const { data } = await api.get(`/admin/reels?only_visible=${onlyVisible}`);
  return data;
}

/** Ролик не удаляем: жалоба могла быть ложной, вернуть удалённое нечем. */
export async function moderateReel(
  reelId: string,
  action: "hide" | "show"
): Promise<void> {
  await api.post("/admin/reels/action", { reel_id: reelId, action });
}

/* ── Истории ────────────────────────────────────────────────────*/

/**
 * История в очереди модерации.
 *
 * Живёт сутки: по expires_at видно, показывается ли кадр ещё или уже
 * ждёт уборки — истёкшую снимать поздно и незачем.
 */
export interface AdminStory {
  id: string;
  author_id: string;
  author_name: string;
  media_url: string;
  caption: string;
  /** matches — видят только пары, everyone — любой открывший анкету. */
  audience: string;
  views_count: number;
  is_hidden: boolean;
  created_at: string | null;
  expires_at: string | null;
}

export async function getAdminStories(onlyVisible = false): Promise<AdminStory[]> {
  const { data } = await api.get(`/admin/stories?only_visible=${onlyVisible}`);
  return data;
}

/** Историю не удаляем по той же причине, что и ролик. */
export async function moderateStory(
  storyId: string,
  action: "hide" | "show"
): Promise<void> {
  await api.post("/admin/stories/action", { story_id: storyId, action });
}

/* ── Рассылка через бота ────────────────────────────────────────*/

/**
 * Рассылка. API только ставит задачу, шлёт бот; прогресс (sent/failed)
 * бот пишет в ту же строку — список перечитывают, пока status = running.
 *
 * Статусы: queued — бот ещё не взял; running — шлёт; done — закончил
 * (частные сбои — в failed); error — не запустилась или упала целиком.
 */
export interface AdminBroadcast {
  id: string;
  created_by: string;
  created_by_name: string;
  text: string;
  /** all — всем живым с Telegram; test — только себе, посмотреть глазами получателя. */
  segment: string;
  status: string;
  total: number;
  sent: number;
  failed: number;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export async function createBroadcast(
  text: string,
  segment: "all" | "test"
): Promise<AdminBroadcast> {
  const { data } = await api.post("/admin/broadcast", { text, segment });
  return data;
}

export async function getBroadcasts(page = 1, limit = 20): Promise<AdminBroadcast[]> {
  const { data } = await api.get("/admin/broadcasts", { params: { page, limit } });
  return data;
}

/* ── Метрики ────────────────────────────────────────────────────*/

/** Недельная когорта регистраций. Доли 0..1; null — окно ещё не закрыто. */
export interface RetentionCohort {
  /** Понедельник ISO-недели, "2026-08-17". */
  week: string;
  size: number;
  d1: number | null;
  d7: number | null;
  d30: number | null;
}

/**
 * Выручка одной валюты. Суммы в минорных единицах:
 * XTR — звёзды, RUB — копейки, USDT — сотые.
 */
export interface RevenueRow {
  currency: string;
  count_30d: number;
  amount_30d: number;
  count_total: number;
  amount_total: number;
  payers_total: number;
}

export interface AdminMetrics {
  dau: number;
  wau: number;
  mau: number;
  /** dau/mau, 0..1; 0 при пустом mau. */
  stickiness: number;
  cohorts: RetentionCohort[];
  revenue: RevenueRow[];
  /**
   * С какого момента платежи пишутся с суммами; null — таких ещё нет.
   * Платежи App Store сумм не имеют — их выручку считает App Store Connect.
   */
  revenue_since: string | null;
}

export async function getAdminMetrics(): Promise<AdminMetrics> {
  const { data } = await api.get("/admin/metrics");
  return data;
}

/* ── Промокоды ──────────────────────────────────────────────────*/

export interface AdminPromo {
  id: string;
  /** Верхний регистр, латиница и цифры; показывается как есть. */
  code: string;
  tier: string;
  days: number;
  /** 0 — без лимита активаций. */
  max_uses: number;
  used_count: number;
  expires_at: string | null;
  /** Выключенный код не активируется, но история активаций остаётся. */
  is_active: boolean;
  comment: string;
  created_at: string | null;
}

export async function createPromo(input: {
  tier: string;
  days: number;
  max_uses: number;
  /** Пусто — сервер сгенерирует сам. */
  code?: string;
  expires_at?: string | null;
  comment?: string;
}): Promise<AdminPromo> {
  const { data } = await api.post("/admin/promos", input);
  return data;
}

export async function getPromos(page = 1, limit = 50): Promise<AdminPromo[]> {
  const { data } = await api.get("/admin/promos", { params: { page, limit } });
  return data;
}

export async function setPromoActive(
  promoId: string,
  isActive: boolean
): Promise<AdminPromo> {
  const { data } = await api.patch(`/admin/promos/${promoId}`, {
    is_active: isActive,
  });
  return data;
}
