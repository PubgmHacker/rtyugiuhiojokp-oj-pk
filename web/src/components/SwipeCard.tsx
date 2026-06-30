import { useState, useRef } from "react";
import { motion, useMotionValue, useTransform, type PanInfo } from "framer-motion";
import { MapPin, Sparkles, X, Heart } from "lucide-react";
import type { DeckProfile } from "../lib/api";
import { hapticFeedback } from "../lib/telegram";

interface SwipeCardProps {
  profile: DeckProfile;
  onSwipe: (direction: "left" | "right" | "up", profile: DeckProfile) => void;
  isTop: boolean;
  index: number;
}

export default function SwipeCard({ profile, onSwipe, isTop, index }: SwipeCardProps) {
  const [photoIndex, setPhotoIndex] = useState(0);
  const cardRef = useRef<HTMLDivElement>(null);

  const x = useMotionValue(0);
  const y = useMotionValue(0);

  const rotate = useTransform(x, [-200, 200], [-18, 18]);
  const likeOpacity = useTransform(x, [0, 100], [0, 1]);
  const nopeOpacity = useTransform(x, [-100, 0], [1, 0]);
  const superOpacity = useTransform(y, [-100, 0], [1, 0]);

  const photos = profile.photos?.length ? profile.photos : [];
  const currentPhoto = photos[photoIndex] || "";

  const handleDragEnd = (_: unknown, info: PanInfo) => {
    const threshold = 100;
    const velocity = 500;

    if (info.offset.x > threshold || info.velocity.x > velocity) {
      hapticFeedback("medium");
      onSwipe("right", profile);
    } else if (info.offset.x < -threshold || info.velocity.x < -velocity) {
      hapticFeedback("medium");
      onSwipe("left", profile);
    } else if (info.offset.y < -threshold || info.velocity.y < -velocity) {
      hapticFeedback("heavy");
      onSwipe("up", profile);
    }
  };

  const nextPhoto = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (photoIndex < photos.length - 1) setPhotoIndex(photoIndex + 1);
  };

  const prevPhoto = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (photoIndex > 0) setPhotoIndex(photoIndex - 1);
  };

  if (!isTop) {
    // Stacked background cards
    return (
      <motion.div
        className="absolute inset-0 rounded-3xl overflow-hidden bg-surface"
        style={{
          zIndex: index,
          scale: 1 - index * 0.05,
          translateY: index * 12,
        }}
      >
        {currentPhoto && (
          <img src={currentPhoto} alt={profile.display_name} className="w-full h-full object-cover" />
        )}
      </motion.div>
    );
  }

  return (
    <motion.div
      ref={cardRef}
      className="absolute inset-0 rounded-3xl overflow-hidden bg-surface swipe-card-glow cursor-grab active:cursor-grabbing select-none"
      style={{ x, y, rotate, zIndex: 10 }}
      drag={isTop}
      dragSnapToOrigin
      onDragEnd={handleDragEnd}
      whileTap={{ cursor: "grabbing" }}
    >
      {/* Photo */}
      {currentPhoto ? (
        <img
          src={currentPhoto}
          alt={profile.display_name}
          className="w-full h-full object-cover pointer-events-none"
          draggable={false}
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center bg-gradient-to-br from-[#1a1a2e] to-[#0a0a1a]">
          <div className="text-6xl opacity-30">👤</div>
        </div>
      )}

      {/* Gradient overlay */}
      <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-black/30 pointer-events-none" />

      {/* Photo navigation */}
      {photos.length > 1 && (
        <>
          <div className="absolute top-2 left-0 right-0 flex gap-1 px-3 pointer-events-none">
            {photos.map((_, i) => (
              <div
                key={i}
                className={`h-1 flex-1 rounded-full transition-all ${
                  i === photoIndex ? "bg-white" : "bg-white/30"
                }`}
              />
            ))}
          </div>
          <div className="absolute inset-0 flex">
            <div className="flex-1" onClick={prevPhoto} />
            <div className="flex-1" onClick={nextPhoto} />
          </div>
        </>
      )}

      {/* LIKE / NOPE / SUPER overlays */}
      <motion.div
        className="absolute top-12 left-6 border-4 border-success rounded-2xl px-4 py-2 rotate-[-20deg] pointer-events-none"
        style={{ opacity: likeOpacity }}
      >
        <span className="text-success text-3xl font-black tracking-wider">LIKE</span>
      </motion.div>

      <motion.div
        className="absolute top-12 right-6 border-4 border-danger rounded-2xl px-4 py-2 rotate-[20deg] pointer-events-none"
        style={{ opacity: nopeOpacity }}
      >
        <span className="text-danger text-3xl font-black tracking-wider">NOPE</span>
      </motion.div>

      <motion.div
        className="absolute top-12 left-1/2 -translate-x-1/2 border-4 border-warn rounded-2xl px-4 py-2 pointer-events-none"
        style={{ opacity: superOpacity }}
      >
        <span className="text-warn text-2xl font-black">SUPER</span>
      </motion.div>

      {/* Info */}
      <div className="absolute bottom-0 left-0 right-0 p-6 text-white pointer-events-none">
        <div className="flex items-end gap-3 mb-2">
          <h2 className="text-3xl font-bold">{profile.display_name}</h2>
          {profile.age && <span className="text-2xl font-light opacity-90">{profile.age}</span>}
        </div>

        {profile.city && (
          <div className="flex items-center gap-1 text-sm opacity-80 mb-2">
            <MapPin size={14} />
            <span>
              {profile.city}
              {profile.distance != null && ` • ${profile.distance} км`}
            </span>
          </div>
        )}

        {profile.ai_bio && (
          <div className="flex items-start gap-1 text-sm mb-2 text-accent">
            <Sparkles size={14} className="mt-0.5 shrink-0" />
            <span className="italic">{profile.ai_bio}</span>
          </div>
        )}

        {profile.bio && (
          <p className="text-sm opacity-90 line-clamp-2 mb-2">{profile.bio}</p>
        )}

        {profile.interests?.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {profile.interests.slice(0, 5).map((interest, i) => (
              <span
                key={i}
                className="text-xs px-2 py-1 rounded-full bg-white/20 backdrop-blur-sm"
              >
                {interest}
              </span>
            ))}
          </div>
        )}
      </div>
    </motion.div>
  );
}
