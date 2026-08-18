import { create } from "zustand";
import { logoutServerSide } from "./api";
import type { UserProfile, DeckProfile, MatchResponse } from "./api";

interface AppState {
  user: UserProfile | null;
  token: string | null;
  deck: DeckProfile[];
  matches: MatchResponse[];
  isLoading: boolean;
  isOnboarded: boolean;
  /** Счётчик для бейджа на вкладке «Лайки». */
  unreadLikes: number;
  /** Счётчик для бейджа на вкладке «Чаты» — непрочитанные сообщения. */
  unreadMessages: number;

  setUser: (user: UserProfile | null) => void;
  setToken: (token: string | null) => void;
  setDeck: (deck: DeckProfile[]) => void;
  addDeck: (profiles: DeckProfile[]) => void;
  removeDeckProfile: (id: string) => void;
  setMatches: (matches: MatchResponse[]) => void;
  addMatch: (match: MatchResponse) => void;
  setLoading: (loading: boolean) => void;
  setOnboarded: (onboarded: boolean) => void;
  setUnreadLikes: (count: number) => void;
  setUnreadMessages: (count: number) => void;
  logout: () => void;
}

// Профиль читаем синхронно, как и токен: если отложить в useEffect, первый
// рендер видит token без user, и редирект с /login уводит зарегистрированного
// человека в онбординг с пустыми полями.
function сохранённыйПрофиль(): UserProfile | null {
  const raw = localStorage.getItem("sd_user");
  if (!raw) return null;
  try {
    return JSON.parse(raw) as UserProfile;
  } catch {
    localStorage.removeItem("sd_user");
    return null;
  }
}

const начальныйПрофиль = сохранённыйПрофиль();

export const useStore = create<AppState>((set) => ({
  user: начальныйПрофиль,
  token: localStorage.getItem("sd_token"),
  deck: [],
  matches: [],
  isLoading: false,
  isOnboarded: !!(начальныйПрофиль?.display_name && начальныйПрофиль?.photos?.length),
  unreadLikes: 0,
  unreadMessages: 0,

  setUser: (user) => {
    if (user) localStorage.setItem("sd_user", JSON.stringify(user));
    else localStorage.removeItem("sd_user");
    set({ user, isOnboarded: !!(user?.display_name && user?.photos?.length) });
  },
  setToken: (token) => {
    if (token) localStorage.setItem("sd_token", token);
    else localStorage.removeItem("sd_token");
    set({ token });
  },
  setDeck: (deck) => set({ deck }),
  addDeck: (profiles) => set((s) => ({ deck: [...s.deck, ...profiles] })),
  removeDeckProfile: (id) => set((s) => ({ deck: s.deck.filter((p) => p.id !== id) })),
  setMatches: (matches) => set({ matches }),
  addMatch: (match) => set((s) => ({ matches: [match, ...s.matches] })),
  setLoading: (isLoading) => set({ isLoading }),
  setOnboarded: (isOnboarded) => set({ isOnboarded }),
  setUnreadLikes: (unreadLikes) => set({ unreadLikes }),
  setUnreadMessages: (unreadMessages) => set({ unreadMessages }),
  logout: () => {
    // Сервер должен погасить токен, пока он ещё в localStorage: без этого
    // он остаётся годным до конца срока, даже если выйти на чужом устройстве
    void logoutServerSide();
    localStorage.removeItem("sd_token");
    localStorage.removeItem("sd_user");
    set({
      user: null,
      token: null,
      deck: [],
      matches: [],
      isOnboarded: false,
      unreadLikes: 0,
      unreadMessages: 0,
    });
  },
}));
