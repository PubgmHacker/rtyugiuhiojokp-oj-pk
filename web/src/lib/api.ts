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
}

export interface MatchResponse {
  id: string;
  match_score?: number | null;
  ai_reason?: string | null;
  created_at?: string | null;
  partner: UserProfile;
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

export async function likeProfile(targetId: string, type: "like" | "superlike" | "pass" = "like"): Promise<{
  liked: boolean;
  matched: boolean;
  match?: MatchResponse;
}> {
  const { data } = await api.post("/likes", { target_id: targetId, type });
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
