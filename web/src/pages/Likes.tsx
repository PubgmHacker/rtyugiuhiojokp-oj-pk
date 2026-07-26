import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Heart, X, Sparkles } from "lucide-react";
import { getLikesReceived, likeProfile, type UserProfile } from "../lib/api";
import { hapticFeedback } from "../lib/telegram";
import MatchModal from "../components/MatchModal";

interface MatchData {
  partnerName: string;
  partnerPhoto?: string;
  score?: number;
  reason?: string;
  matchId?: string;
}

export default function Likes() {
  const [likes, setLikes] = useState<UserProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [matchData, setMatchData] = useState<MatchData | null>(null);

  useEffect(() => {
    load();
  }, []);

  const load = async () => {
    try {
      setLikes(await getLikesReceived());
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleAction = async (profile: UserProfile, type: "like" | "pass") => {
    setLikes((prev) => prev.filter((p) => p.id !== profile.id));
    try {
      const result = await likeProfile(profile.id, type);
      if (result.matched && result.match) {
        hapticFeedback("success");
        setMatchData({
          partnerName: profile.display_name,
          partnerPhoto: profile.photos?.[0],
          score: result.match.match_score ?? undefined,
          reason: result.match.ai_reason ?? undefined,
          matchId: result.match.id,
        });
      }
    } catch (e) {
      console.error(e);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-accent" />
      </div>
    );
  }

  return (
    <div className="min-h-screen max-w-md mx-auto p-4">
      <h1 className="text-2xl font-bold mb-2 flex items-center gap-2">
        <Sparkles className="text-warn" />
        Вы понравились ({likes.length})
      </h1>
      <p className="text-sm text-text-muted mb-6">
        Эти люди уже поставили вам лайк — ответный лайк сразу даст мэтч
      </p>

      {likes.length === 0 ? (
        <div className="text-center py-20">
          <Heart size={64} className="mx-auto text-text-muted mb-4" />
          <h2 className="text-xl font-semibold mb-2">Пока никто не лайкнул</h2>
          <p className="text-text-muted mb-6">Заполните анкету получше и продолжайте свайпать!</p>
          <Link
            to="/discover"
            className="inline-block px-6 py-3 bg-accent text-white rounded-full font-semibold"
          >
            К анкетам
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {likes.map((p, i) => (
            <motion.div
              key={p.id}
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: i * 0.05 }}
              className="relative aspect-[3/4] rounded-2xl overflow-hidden bg-surface"
            >
              {p.photos?.[0] ? (
                <img src={p.photos[0]} alt={p.display_name} className="w-full h-full object-cover" />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-5xl opacity-30">👤</div>
              )}
              <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-transparent to-transparent" />
              <div className="absolute bottom-0 left-0 right-0 p-3 text-white">
                <p className="font-semibold truncate">
                  {p.display_name}
                  {p.age ? `, ${p.age}` : ""}
                </p>
                {p.city && <p className="text-xs opacity-75 truncate">{p.city}</p>}
                <div className="flex gap-2 mt-2">
                  <button
                    onClick={() => handleAction(p, "pass")}
                    className="flex-1 py-2 bg-white/15 backdrop-blur-sm rounded-full flex items-center justify-center"
                  >
                    <X size={18} className="text-danger" strokeWidth={3} />
                  </button>
                  <button
                    onClick={() => handleAction(p, "like")}
                    className="flex-1 py-2 bg-white/15 backdrop-blur-sm rounded-full flex items-center justify-center"
                  >
                    <Heart size={18} className="text-success" fill="currentColor" />
                  </button>
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      )}

      <MatchModal data={matchData} onClose={() => setMatchData(null)} />
    </div>
  );
}
