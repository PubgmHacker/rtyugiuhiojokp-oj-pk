import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Heart, MessageCircle } from "lucide-react";
import { getMatches, type MatchResponse } from "../lib/api";

export default function Matches() {
  const [matches, setMatches] = useState<MatchResponse[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadMatches();
  }, []);

  const loadMatches = async () => {
    try {
      const data = await getMatches();
      setMatches(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
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
      <h1 className="text-2xl font-bold mb-6 flex items-center gap-2">
        <Heart className="text-accent" fill="currentColor" />
        Мэтчи ({matches.length})
      </h1>

      {matches.length === 0 ? (
        <div className="text-center py-20">
          <Heart size={64} className="mx-auto text-text-muted mb-4" />
          <h2 className="text-xl font-semibold mb-2">Пока нет мэтчей</h2>
          <p className="text-text-muted mb-6">Продолжай ставить лайки!</p>
          <Link
            to="/discover"
            className="inline-block px-6 py-3 bg-accent text-white rounded-full font-semibold"
          >
            Искать дальше
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {matches.map((m, i) => (
            <motion.div
              key={m.id}
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: i * 0.05 }}
            >
              <Link
                to={`/chat/${m.id}`}
                className="block relative aspect-[3/4] rounded-2xl overflow-hidden group"
              >
                {m.partner.photos?.[0] ? (
                  <img
                    src={m.partner.photos[0]}
                    alt={m.partner.display_name}
                    className="w-full h-full object-cover group-hover:scale-105 transition"
                  />
                ) : (
                  <div className="w-full h-full bg-surface flex items-center justify-center">
                    <Heart size={40} className="text-text-muted" />
                  </div>
                )}
                <div className="absolute inset-0 bg-gradient-to-t from-black/80 to-transparent" />
                <div className="absolute bottom-0 left-0 right-0 p-3 text-white">
                  <p className="font-semibold truncate">{m.partner.display_name}</p>
                  {m.match_score != null && (
                    <p className="text-xs text-warn">✨ {m.match_score}% совместимость</p>
                  )}
                </div>
                <div className="absolute top-2 right-2 w-8 h-8 bg-black/40 rounded-full flex items-center justify-center backdrop-blur-sm">
                  <MessageCircle size={16} className="text-white" />
                </div>
              </Link>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}
