import { useState, useCallback, useEffect, memo } from "react";
import {
  motion,
  useMotionValue,
  useTransform,
  useMotionTemplate,
  type PanInfo,
  type MotionValue,
} from "framer-motion";
import { MapPin, Sparkles } from "lucide-react";
import type { DeckProfile } from "../lib/api";
import { haptic } from "../lib/haptics";
import { VerifiedBadge } from "./ui";
import { GOALS, SUBCULTURES, optionLabel } from "../lib/profileOptions";

export type SwipeDirection = "left" | "right" | "up";

interface SwipeCardProps {
  profile: DeckProfile;
  onSwipe: (direction: SwipeDirection, profile: DeckProfile) => void;
  isTop: boolean;
  index: number;
}

/** Порог смещения и скорости, после которого жест считается свайпом. */
const OFFSET_THRESHOLD = 92;
const VELOCITY_THRESHOLD = 420;

/** Пружина, близкая к отклику нативного iOS. */
const SPRING = { type: "spring" as const, stiffness: 380, damping: 34, mass: 0.9 };

function SwipeCardImpl({ profile, onSwipe, isTop, index }: SwipeCardProps) {
  const [photoIndex, setPhotoIndex] = useState(0);
  const [loadedPhotos, setLoadedPhotos] = useState<Record<number, boolean>>({});

  const x = useMotionValue(0);
  const y = useMotionValue(0);

  const rotate = useTransform(x, [-240, 0, 240], [-16, 0, 16]);
  const likeOpacity = useTransform(x, [20, 110], [0, 1]);
  const nopeOpacity = useTransform(x, [-110, -20], [1, 0]);
  const superOpacity = useTransform(y, [-110, -20], [1, 0]);

  // Подсветка карточки в сторону жеста — читаемая обратная связь
  const glowOpacity = useTransform(x, [-160, 0, 160], [0.5, 0, 0.5]);
  const glowColor = useTransform(x, (v: number) =>
    v < 0 ? "var(--color-danger)" : "var(--color-success)"
  );
  const glowShadow = useMotionTemplate`inset 0 0 90px 12px ${glowColor}`;

  const photos = profile.photos?.length ? profile.photos : [];
  const hasPhotos = photos.length > 0;

  const handleDragEnd = useCallback(
    (_: unknown, info: PanInfo) => {
      const { offset, velocity } = info;

      // Вертикальный жест проверяем первым: суперлайк должен быть
      // достижим, даже если палец немного ушёл в сторону
      if (
        offset.y < -OFFSET_THRESHOLD &&
        Math.abs(offset.y) > Math.abs(offset.x) &&
        velocity.y < 0
      ) {
        haptic("heavy");
        onSwipe("up", profile);
        return;
      }
      if (offset.x > OFFSET_THRESHOLD || velocity.x > VELOCITY_THRESHOLD) {
        haptic("medium");
        onSwipe("right", profile);
        return;
      }
      if (offset.x < -OFFSET_THRESHOLD || velocity.x < -VELOCITY_THRESHOLD) {
        haptic("light");
        onSwipe("left", profile);
      }
    },
    [onSwipe, profile]
  );

  const showPhoto = useCallback(
    (next: number) => {
      if (next < 0 || next >= photos.length || next === photoIndex) return;
      haptic("select");
      setPhotoIndex(next);
    },
    [photoIndex, photos.length]
  );

  // Прогреваем остальные фото, как только карточка стала верхней: иначе
  // первый тап по краю показывает скелетон, потому что браузер начинает
  // грузить снимок только в момент, когда тот попадает в разметку
  useEffect(() => {
    if (!isTop || photos.length < 2) return;
    photos.slice(1).forEach((src) => {
      const img = new Image();
      img.decoding = "async";
      img.src = src;
    });
  }, [isTop, photos]);

  /* ── Карточки под верхней: только фон, без интерактива ────── */
  if (!isTop) {
    return (
      <motion.div
        aria-hidden
        className="absolute inset-0 rounded-[var(--radius-card)] overflow-hidden bg-surface-2"
        initial={false}
        animate={{ scale: 1 - index * 0.045, y: index * 14, opacity: 1 - index * 0.25 }}
        transition={SPRING}
        style={{ zIndex: 10 - index }}
      >
        {hasPhotos && (
          <img
            src={photos[0]}
            alt=""
            className="w-full h-full object-cover"
            loading="lazy"
            decoding="async"
          />
        )}
        <div className="absolute inset-0 bg-bg/45" />
      </motion.div>
    );
  }

  const currentPhoto = photos[photoIndex];

  return (
    <motion.div
      className="absolute inset-0 rounded-[var(--radius-card)] overflow-hidden
                 bg-surface-2 swipe-card-glow cursor-grab active:cursor-grabbing"
      style={{ x, y, rotate, zIndex: 20 }}
      drag
      dragElastic={0.62}
      dragSnapToOrigin
      dragTransition={{ bounceStiffness: 460, bounceDamping: 38 }}
      onDragEnd={handleDragEnd}
      initial={{ scale: 0.96, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      exit={{ scale: 0.94, opacity: 0, transition: { duration: 0.18 } }}
      transition={SPRING}
    >
      {/* Свечение по направлению жеста */}
      <motion.div
        aria-hidden
        className="absolute inset-0 pointer-events-none rounded-[var(--radius-card)] z-30"
        style={{ opacity: glowOpacity, boxShadow: glowShadow }}
      />

      {/* Фото */}
      {currentPhoto ? (
        <>
          {!loadedPhotos[photoIndex] && <div className="absolute inset-0 skeleton" />}
          <img
            key={currentPhoto}
            src={currentPhoto}
            alt={profile.display_name}
            onLoad={() => setLoadedPhotos((m) => ({ ...m, [photoIndex]: true }))}
            className="w-full h-full object-cover pointer-events-none select-none"
            draggable={false}
            decoding="async"
          />
        </>
      ) : (
        <div
          className="w-full h-full flex items-center justify-center"
          style={{ background: "var(--gradient-placeholder)" }}
        >
          <span className="text-[64px] font-extrabold text-white/25">
            {profile.display_name?.[0]?.toUpperCase() ?? "?"}
          </span>
        </div>
      )}

      {/* Затемнение под текстом */}
      <div className="absolute inset-0 bg-scrim pointer-events-none" />

      {/* Индикатор фото + зоны перелистывания */}
      {photos.length > 1 && (
        <>
          <div className="absolute top-3 left-0 right-0 flex gap-1.5 px-4 z-20 pointer-events-none">
            {photos.map((_, i) => (
              <div
                key={i}
                className={`h-[3px] flex-1 rounded-full transition-all duration-300 ${
                  i === photoIndex ? "bg-white" : "bg-white/25"
                }`}
              />
            ))}
          </div>
          <div className="absolute inset-0 flex z-10">
            <button
              aria-label="Предыдущее фото"
              className="flex-1"
              onClick={() => showPhoto(photoIndex - 1)}
            />
            <button
              aria-label="Следующее фото"
              className="flex-1"
              onClick={() => showPhoto(photoIndex + 1)}
            />
          </div>
        </>
      )}

      {/* Штампы решения */}
      <Stamp
        opacity={likeOpacity}
        tone="success"
        text="ЛАЙК"
        className="top-14 left-6 -rotate-[18deg]"
      />
      <Stamp
        opacity={nopeOpacity}
        tone="danger"
        text="НЕТ"
        className="top-14 right-6 rotate-[18deg]"
      />
      <Stamp
        opacity={superOpacity}
        tone="info"
        text="СУПЕР"
        className="top-1/3 left-1/2 -translate-x-1/2"
      />

      {/* Информация о профиле. Правый отступ — под столбец кнопок действий,
          иначе длинное имя уезжает под них */}
      <div className="absolute bottom-0 left-0 right-0 p-5 pb-6 pr-[84px] z-20 pointer-events-none">
        {profile.match_score != null && (
          <div className="inline-flex items-center gap-1.5 mb-3 px-2.5 py-1 rounded-full glass-strong">
            <Sparkles size={13} className="text-accent" />
            <span className="text-[12px] font-semibold">
              {profile.match_score}% совпадение
            </span>
          </div>
        )}

        <div className="flex items-center gap-2 mb-1.5">
          <h2 className="text-[30px] font-extrabold tracking-[-0.03em] leading-none text-white">
            {profile.display_name}
          </h2>
          {profile.age != null && (
            <span className="text-[26px] font-light text-white/85 leading-none">
              {profile.age}
            </span>
          )}
        </div>

        {(profile.city || profile.distance != null || profile.height_cm != null) && (
          <div className="flex items-center gap-1.5 text-[13px] text-white/75 mb-2.5">
            <MapPin size={13} className="shrink-0" />
            <span className="truncate">
              {[
                profile.city,
                profile.distance != null ? `${profile.distance} км` : null,
                profile.height_cm != null ? `${profile.height_cm} см` : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </span>
          </div>
        )}

        {(profile.goal || profile.subculture || profile.mbti) && (
          <div className="flex flex-wrap gap-1.5 mb-2.5">
            {profile.goal && (
              <span className="text-[12px] px-2.5 py-1 rounded-full glass-strong font-medium">
                {optionLabel(GOALS, profile.goal)}
              </span>
            )}
            {profile.subculture && (
              <span className="text-[12px] px-2.5 py-1 rounded-full glass-strong font-medium">
                {optionLabel(SUBCULTURES, profile.subculture)}
              </span>
            )}
            {/* MBTI показываем кодом: расшифровка «INFJ · Активист» в тесную
                карточку не влезает, а тем, кто ищет по типу, кода достаточно */}
            {profile.mbti && (
              <span className="text-[12px] px-2.5 py-1 rounded-full glass-strong font-medium">
                {profile.mbti}
              </span>
            )}
          </div>
        )}

        {profile.bio && (
          <p className="text-[14px] leading-snug text-white/90 line-clamp-2 mb-3">
            {profile.bio}
          </p>
        )}

        {profile.interests?.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {profile.interests.slice(0, 4).map((interest) => (
              <span
                key={interest}
                className="text-[12px] px-2.5 py-1 rounded-full glass font-medium"
              >
                {interest}
              </span>
            ))}
            {profile.interests.length > 4 && (
              <span className="text-[12px] px-2.5 py-1 rounded-full glass font-medium">
                +{profile.interests.length - 4}
              </span>
            )}
          </div>
        )}
      </div>
    </motion.div>
  );
}

/* ── Штамп решения поверх карточки ──────────────────────────── */

function Stamp({
  opacity,
  tone,
  text,
  className,
}: {
  opacity: MotionValue<number>;
  tone: "success" | "danger" | "info";
  text: string;
  className: string;
}) {
  const color = `var(--color-${tone})`;
  return (
    <motion.div
      aria-hidden
      style={{ opacity, borderColor: color, color }}
      className={`absolute z-30 border-[3px] rounded-2xl px-4 py-1.5 pointer-events-none ${className}`}
    >
      <span className="text-[26px] font-black tracking-[0.06em]">{text}</span>
    </motion.div>
  );
}

/* Карточки перерисовываются часто во время перетаскивания —
   мемоизация заметно снижает нагрузку */
export default memo(SwipeCardImpl);
