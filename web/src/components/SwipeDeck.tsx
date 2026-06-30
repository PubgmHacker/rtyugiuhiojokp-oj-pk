import { useState, useCallback, useEffect } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { X, Heart, Star, Zap, RotateCcw } from "lucide-react";
import type { DeckProfile } from "../lib/api";
import { likeProfile, getDeck } from "../lib/api";
import { useStore } from "../lib/store";
import { hapticFeedback } from "../lib/telegram";
import SwipeCard from "./SwipeCard";
import MatchModal from "./MatchModal";

interface MatchData {
  partnerName: string;
  partnerPhoto?: string;
  score?: number;
  reason?: string;
  matchId?: string;
}

export default function SwipeDeck() {
  const { deck, setDeck, addDeck, removeDeckProfile, addMatch } = useStore();
  const [matchData, setMatchData] = useState<MatchData | null>(null);
  const [isAnimatingOut, setIsAnimatingOut] = useState(false);
  const [lastSwiped, setLastSwiped] = useState<{ profile: DeckProfile; direction: string } | null>(null);

  // Load deck on mount
  useEffect(() => {
    if (deck.length === 0) {
      loadDeck();
    }
  }, []);

  const loadDeck = async () => {
    try {
      const profiles = await getDeck(10);
      setDeck(profiles);
    } catch (e) {
      console.error("Failed to load deck:", e);
    }
  };

  // Preload more when running low
  useEffect(() => {
    if (deck.length <= 3 && deck.length > 0) {
      loadDeck();
    }
  }, [deck.length]);

  const handleSwipe = useCallback(
    async (direction: "left" | "right" | "up", profile: DeckProfile) => {
      if (isAnimatingOut) return;
      setIsAnimatingOut(true);

      setLastSwiped({ profile, direction });

      const likeType = direction === "left" ? "pass" : direction === "up" ? "superlike" : "like";

      // Optimistic removal
      setTimeout(() => {
        removeDeckProfile(profile.id);
        setIsAnimatingOut(false);
      }, 300);

      // Send to API
      if (likeType !== "pass") {
        try {
          const result = await likeProfile(profile.id, likeType as "like" | "superlike");
          if (result.matched && result.match) {
            hapticFeedback("success");
            setMatchData({
              partnerName: profile.display_name,
              partnerPhoto: profile.photos?.[0],
              score: result.match.match_score ?? undefined,
              reason: result.match.ai_reason ?? undefined,
              matchId: result.match.id,
            });
            addMatch(result.match);
          }
        } catch (e) {
          console.error("Like failed:", e);
        }
      } else {
        // Still register the pass
        try {
          await likeProfile(profile.id, "pass");
        } catch (e) {
          console.error("Pass failed:", e);
        }
      }
    },
    [isAnimatingOut, removeDeckProfile, addMatch]
  );

  // Button handlers
  const handleButtonSwipe = (direction: "left" | "right" | "up") => {
    const topProfile = deck[0];
    if (topProfile) handleSwipe(direction, topProfile);
  };

  const handleRewind = () => {
    if (lastSwiped) {
      setDeck([lastSwiped.profile, ...deck]);
      setLastSwiped(null);
      hapticFeedback("light");
    }
  };

  if (deck.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
        <motion.div
          animate={{ scale: [1, 1.1, 1] }}
          transition={{ repeat: Infinity, duration: 2 }}
          className="text-6xl mb-4"
        >
          💔
        </motion.div>
        <h2 className="text-xl font-bold mb-2">Анкеты закончились</h2>
        <p className="text-text-muted mb-6">Попробуйте обновить позже или измените настройки поиска</p>
        <button
          onClick={loadDeck}
          className="px-6 py-3 bg-accent text-white rounded-full font-semibold hover:bg-accent/90 transition"
        >
          Обновить
        </button>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col px-4 py-4 max-w-md mx-auto w-full">
      {/* Card stack */}
      <div className="relative flex-1 mb-4">
        <AnimatePresence>
          {deck.slice(0, 3).reverse().map((profile, idx) => {
            const realIndex = deck.length - 1 - idx;
            const isTop = idx === deck.length - 1;
            return (
              <SwipeCard
                key={profile.id}
                profile={profile}
                onSwipe={handleSwipe}
                isTop={isTop}
                index={realIndex}
              />
            );
          })}
        </AnimatePresence>
      </div>

      {/* Action buttons */}
      <div className="flex items-center justify-center gap-3 sm:gap-4 safe-bottom">
        <ActionButton onClick={handleRewind} disabled={!lastSwiped} className="bg-surface text-warn" size="sm">
          <RotateCcw size={20} />
        </ActionButton>

        <ActionButton onClick={() => handleButtonSwipe("left")} className="bg-surface text-danger" size="md">
          <X size={28} strokeWidth={3} />
        </ActionButton>

        <ActionButton onClick={() => handleButtonSwipe("up")} className="bg-surface text-warn" size="sm">
          <Star size={22} fill="currentColor" />
        </ActionButton>

        <ActionButton onClick={() => handleButtonSwipe("right")} className="bg-surface text-success" size="md">
          <Heart size={26} fill="currentColor" />
        </ActionButton>

        <ActionButton onClick={() => {}} className="bg-surface text-accent" size="sm">
          <Zap size={20} />
        </ActionButton>
      </div>

      {/* Match modal */}
      <MatchModal data={matchData} onClose={() => setMatchData(null)} />
    </div>
  );
}

function ActionButton({
  children,
  onClick,
  disabled,
  className = "",
  size = "md",
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  className?: string;
  size?: "sm" | "md";
}) {
  const sizeClass = size === "md" ? "w-14 h-14" : "w-11 h-11";
  return (
    <motion.button
      whileTap={{ scale: 0.85 }}
      onClick={onClick}
      disabled={disabled}
      className={`${sizeClass} ${className} rounded-full flex items-center justify-center shadow-lg disabled:opacity-30 transition border-2 border-white/10`}
    >
      {children}
    </motion.button>
  );
}
