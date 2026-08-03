import { create } from "zustand";
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
  logout: () => void;
}

export const useStore = create<AppState>((set) => ({
  user: null,
  token: localStorage.getItem("sd_token"),
  deck: [],
  matches: [],
  isLoading: false,
  isOnboarded: false,
  unreadLikes: 0,

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
  logout: () => {
    localStorage.removeItem("sd_token");
    localStorage.removeItem("sd_user");
    set({
      user: null,
      token: null,
      deck: [],
      matches: [],
      isOnboarded: false,
      unreadLikes: 0,
    });
  },
}));
