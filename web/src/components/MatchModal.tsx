import { motion, AnimatePresence } from "framer-motion";
import { Heart, Sparkles } from "lucide-react";

interface MatchModalProps {
  data: {
    partnerName: string;
    partnerPhoto?: string;
    score?: number;
    reason?: string;
    matchId?: string;
  } | null;
  onClose: () => void;
}

export default function MatchModal({ data, onClose }: MatchModalProps) {
  return (
    <AnimatePresence>
      {data && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-6"
          onClick={onClose}
        >
          {/* Floating hearts */}
          {[...Array(6)].map((_, i) => (
            <motion.div
              key={i}
              className="absolute text-accent"
              initial={{
                x: (Math.random() - 0.5) * 300,
                y: 200,
                opacity: 0,
              }}
              animate={{
                y: -300,
                opacity: [0, 1, 0],
                rotate: (Math.random() - 0.5) * 60,
              }}
              transition={{
                duration: 2 + Math.random(),
                repeat: Infinity,
                delay: i * 0.3,
              }}
            >
              <Heart size={24 + Math.random() * 20} fill="currentColor" />
            </motion.div>
          ))}

          <motion.div
            initial={{ scale: 0.5, opacity: 0, y: 50 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.5, opacity: 0 }}
            transition={{ type: "spring", damping: 15 }}
            className="relative bg-gradient-to-b from-[#1a1a2e] to-[#0a0a1a] rounded-3xl p-8 max-w-sm w-full text-center border border-accent/30"
            onClick={(e) => e.stopPropagation()}
          >
            <motion.div
              animate={{ scale: [1, 1.2, 1] }}
              transition={{ repeat: Infinity, duration: 1.2 }}
              className="flex justify-center mb-4"
            >
              <div className="w-20 h-20 rounded-full bg-accent/20 flex items-center justify-center">
                <Heart className="text-accent heart-beat" size={40} fill="currentColor" />
              </div>
            </motion.div>

            <h2 className="text-3xl font-bold mb-1 bg-gradient-to-r from-accent to-warn bg-clip-text text-transparent">
              Это мэтч!
            </h2>
            <p className="text-lg mb-6 text-text-muted">
              Вы понравились друг другу с <span className="text-accent font-semibold">{data.partnerName}</span>
            </p>

            {/* Partner photo */}
            {data.partnerPhoto && (
              <div className="flex justify-center mb-6">
                <img
                  src={data.partnerPhoto}
                  alt={data.partnerName}
                  className="w-32 h-32 rounded-full object-cover border-4 border-accent/50"
                />
              </div>
            )}

            {/* AI score */}
            {data.score != null && (
              <div className="mb-6 p-4 bg-accent/10 rounded-2xl">
                <div className="flex items-center justify-center gap-2 mb-2">
                  <Sparkles size={18} className="text-warn" />
                  <span className="font-bold text-lg">Совместимость: {data.score}/100</span>
                </div>
                {data.reason && <p className="text-sm text-text-muted italic">{data.reason}</p>}
              </div>
            )}

            <div className="flex flex-col gap-3">
              <a
                href={data.matchId ? `/chat/${data.matchId}` : "/matches"}
                className="w-full py-3 bg-gradient-to-r from-accent to-warn text-white font-bold rounded-full hover:opacity-90 transition"
              >
                Написать сообщение
              </a>
              <button
                onClick={onClose}
                className="w-full py-3 bg-surface text-text-muted font-medium rounded-full hover:bg-surface/80 transition"
              >
                Продолжить поиск
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
