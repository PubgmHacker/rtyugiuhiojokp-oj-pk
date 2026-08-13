import { useEffect, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { Heart, Sparkles, MessageCircle } from "lucide-react";
import { haptic } from "../lib/haptics";
import { Button } from "./ui";
import { useStore } from "../lib/store";

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

/** Разлетающиеся сердечки: позиции фиксируем один раз, чтобы они
 *  не прыгали при каждой перерисовке. */
const CONFETTI = Array.from({ length: 14 }, (_, i) => ({
  id: i,
  x: (i % 7) * 56 - 168 + (i % 3) * 14,
  size: 14 + ((i * 7) % 22),
  delay: (i % 5) * 0.18,
  duration: 2.4 + (i % 4) * 0.45,
  rotate: ((i % 5) - 2) * 26,
}));

export default function MatchModal({ data, onClose }: MatchModalProps) {
  const navigate = useNavigate();
  const me = useStore((s) => s.user);
  const myPhoto = me?.photos?.[0];

  const isOpen = !!data;

  // Закрытие по Escape — привычно на вебе и в Telegram Desktop
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen, onClose]);

  const confetti = useMemo(() => CONFETTI, []);

  return (
    <AnimatePresence>
      {data && (
        <motion.div
          role="dialog"
          aria-modal="true"
          aria-label="Взаимная симпатия"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.22 }}
          onClick={onClose}
          className="fixed inset-0 z-50 flex items-center justify-center p-6
                     bg-black/75 backdrop-blur-xl safe-top safe-bottom"
        >
          {/* Сердечки на фоне */}
          <div className="absolute inset-0 overflow-hidden pointer-events-none">
            {confetti.map((c) => (
              <motion.div
                key={c.id}
                className="absolute left-1/2 bottom-0 text-accent"
                initial={{ x: c.x, y: 40, opacity: 0, rotate: 0 }}
                animate={{
                  y: -window.innerHeight * 0.85,
                  opacity: [0, 0.9, 0],
                  rotate: c.rotate,
                }}
                transition={{
                  duration: c.duration,
                  repeat: Infinity,
                  delay: c.delay,
                  ease: "easeOut",
                }}
              >
                <Heart size={c.size} fill="currentColor" />
              </motion.div>
            ))}
          </div>

          <motion.div
            initial={{ scale: 0.86, opacity: 0, y: 32 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.9, opacity: 0, y: 16 }}
            transition={{ type: "spring", stiffness: 340, damping: 26 }}
            onClick={(e) => e.stopPropagation()}
            className="relative w-full max-w-[360px] rounded-[var(--radius-sheet)]
                       bg-bg-elevated border border-hairline card-shadow
                       px-6 pt-8 pb-6 text-center"
          >
            {/* Две аватарки внахлёст */}
            <div className="flex items-center justify-center mb-6">
              <Avatar src={myPhoto} fallback={me?.display_name} className="-mr-5" />
              <motion.div
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ delay: 0.18, type: "spring", stiffness: 480, damping: 18 }}
                className="relative z-10 w-12 h-12 rounded-full btn-torch
                           flex items-center justify-center glow-rose"
              >
                <Heart size={22} fill="#fff" className="text-white heart-beat" />
              </motion.div>
              <Avatar src={data.partnerPhoto} fallback={data.partnerName} className="-ml-5" />
            </div>

            <h2 className="text-[30px] font-extrabold tracking-[-0.03em] text-gradient mb-2">
              Взаимно!
            </h2>
            <p className="text-[15px] text-text-secondary leading-relaxed mb-6">
              Вы с{" "}
              <span className="text-text font-semibold">{data.partnerName}</span>{" "}
              понравились друг другу
            </p>

            {data.score != null && (
              <div className="mb-6 p-4 rounded-[var(--radius-tile)] bg-surface border border-hairline">
                <div className="flex items-center justify-center gap-2 mb-1.5">
                  <Sparkles size={16} className="text-accent" />
                  <span className="font-bold text-[15px]">
                    Совместимость {data.score}%
                  </span>
                </div>
                {data.reason && (
                  <p className="text-[13px] text-text-muted leading-relaxed">
                    {data.reason}
                  </p>
                )}
              </div>
            )}

            <div className="flex flex-col gap-2.5">
              <Button
                size="lg"
                fullWidth
                hapticKind="success"
                onClick={() => {
                  onClose();
                  navigate(data.matchId ? `/chat/${data.matchId}` : "/matches");
                }}
              >
                <MessageCircle size={18} />
                Написать первым
              </Button>
              <Button
                variant="ghost"
                size="md"
                fullWidth
                onClick={() => {
                  haptic("light");
                  onClose();
                }}
              >
                Продолжить поиск
              </Button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function Avatar({
  src,
  fallback,
  className = "",
}: {
  src?: string;
  fallback?: string;
  className?: string;
}) {
  return (
    <div
      className={`w-[84px] h-[84px] rounded-full overflow-hidden avatar-ring
                  shrink-0 ${className}`}
    >
      {src ? (
        <img
          src={src}
          alt=""
          className="w-full h-full object-cover rounded-full"
          decoding="async"
        />
      ) : (
        <div
          className="w-full h-full rounded-full flex items-center justify-center text-2xl font-bold text-white/70"
          style={{ background: "var(--gradient-placeholder)" }}
        >
          {fallback?.[0]?.toUpperCase() ?? "?"}
        </div>
      )}
    </div>
  );
}
