/**
 * Полноэкранный просмотр чужой анкеты: все фото, полное био и интересы.
 *
 * До него решение «нравится / нет» принималось по одному кадру: тайл в
 * «кто лайкнул» показывает первое фото, а из чата профиль было не открыть
 * вообще (аудит, блок «Продукт»). Данные уже на клиенте: и раскрытый лайк,
 * и партнёр мэтча приходят полным UserProfile
 * (api/routers/likes.py::_profile_to_user) — отдельный эндпоинт не нужен,
 * а закрытым (is_locked) карточкам открывать нечего.
 *
 * Компонент презентационный: действия (лайк, письмо) передают через
 * `actions` — в чате их нет, в лайках это те же решения, что на тайле.
 */

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { MapPin, Ruler, X } from "lucide-react";
import type { UserProfile } from "../lib/api";
import { haptic } from "../lib/haptics";
import { decorStyle } from "../lib/decor";
import { GOALS, RELATION_TYPES, SUBCULTURES, optionLabel } from "../lib/profileOptions";
import { VerifiedBadge } from "./ui";

interface Props {
  profile: UserProfile | null;
  onClose: () => void;
  /** Кнопки решения снизу; чат их не передаёт — там мэтч уже случился. */
  actions?: ReactNode;
}

export default function ProfileSheet({ profile, onClose, actions }: Props) {
  return (
    <AnimatePresence>
      {profile && (
        // key: смена человека без закрытия шторки обязана сбросить фото-пейджер
        <Просмотр key={profile.id} profile={profile} onClose={onClose} actions={actions} />
      )}
    </AnimatePresence>
  );
}

function Просмотр({
  profile,
  onClose,
  actions,
}: Props & { profile: UserProfile }) {
  const [photoIndex, setPhotoIndex] = useState(0);
  const photos = profile.photos?.length ? profile.photos : [];
  // Видео анкеты — после фото, тем же пейджером. Наружу API отдаёт только
  // публичные URL, но file_id бота на всякий случай не играем
  const videos = (profile.videos ?? []).filter((v) => /^https?:\/\//.test(v));
  const media = [
    ...photos.map((src) => ({ src, video: false })),
    ...videos.map((src) => ({ src, video: true })),
  ];
  const decor = decorStyle(profile.decor);

  const close = useCallback(() => {
    haptic("light");
    onClose();
  }, [onClose]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  // Прогрев остальных кадров, как в деке: без него первый тап по краю
  // показывает пустоту, пока браузер только начинает грузить снимок
  useEffect(() => {
    photos.slice(1).forEach((src) => {
      const img = new Image();
      img.decoding = "async";
      img.src = src;
    });
  }, [photos]);

  const showPhoto = useCallback(
    (next: number) => {
      if (next < 0 || next >= media.length || next === photoIndex) return;
      haptic("select");
      setPhotoIndex(next);
    },
    [photoIndex, media.length]
  );

  const чипы = [
    profile.relation_type && optionLabel(RELATION_TYPES, profile.relation_type),
    profile.goal && optionLabel(GOALS, profile.goal),
    profile.subculture && optionLabel(SUBCULTURES, profile.subculture),
    profile.mbti,
  ].filter(Boolean) as string[];

  return (
    <motion.div
      role="dialog"
      aria-modal="true"
      aria-label={`Профиль ${profile.display_name}`}
      initial={{ y: "100%" }}
      animate={{ y: 0 }}
      exit={{ y: "100%" }}
      transition={{ type: "spring", stiffness: 380, damping: 36 }}
      className="fixed inset-0 z-50 bg-bg overflow-y-auto overscroll-contain"
    >
      {/* Закрытие липнет к верху: на длинной анкете кнопка не имеет права
          уезжать вместе с фото */}
      <div className="sticky top-0 z-30 h-0 safe-top">
        <button
          aria-label="Закрыть профиль"
          onClick={close}
          className="mt-3 ml-3 w-9 h-9 grid place-items-center rounded-full
                     glass-strong text-white/85 active:text-white transition-colors"
        >
          <X size={18} />
        </button>
      </div>

      {/* ── Фото и видео во всю ширину, с пейджером как в деке ─── */}
      <div className="relative w-full aspect-[3/4] max-h-[70vh] overflow-hidden bg-surface-2">
        {media[photoIndex] ? (
          media[photoIndex].video ? (
            // Без звука и с автоплеем, как в деке: анкета — витрина.
            // playsInline обязателен, иначе iOS разворачивает на весь экран
            <video
              key={media[photoIndex].src}
              src={media[photoIndex].src}
              autoPlay
              muted
              loop
              playsInline
              className="w-full h-full object-cover select-none"
            />
          ) : (
            <img
              key={media[photoIndex].src}
              src={media[photoIndex].src}
              alt={profile.display_name}
              decoding="async"
              className="w-full h-full object-cover select-none"
              draggable={false}
            />
          )
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

        <div className="absolute inset-0 bg-scrim pointer-events-none" />

        {decor && (
          <div
            aria-hidden="true"
            className="absolute inset-0 pointer-events-none z-[15]"
            style={{ boxShadow: `${decor.ring}, ${decor.glow}` }}
          />
        )}

        {media.length > 1 && (
          <>
            <div className="absolute top-3 left-0 right-0 flex gap-1.5 px-4 z-20 pointer-events-none">
              {media.map((_, i) => (
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

        <div className="absolute inset-x-0 bottom-0 z-20 p-5 pointer-events-none">
          {/* Наклейка — там же и такая же, как в деке: над именем, на фото */}
          {profile.sticker && (
            <img
              src={profile.sticker}
              alt=""
              draggable={false}
              className="block w-14 h-14 mb-2 -ml-1 -rotate-6 select-none
                         drop-shadow-[0_3px_8px_rgba(0,0,0,.55)]"
            />
          )}
          <div className="flex items-center gap-2">
            <h2 className="text-[28px] font-extrabold tracking-[-0.03em] leading-none text-white">
              {profile.display_name}
            </h2>
            {profile.age != null && (
              <span className="text-[24px] font-light text-white/85 leading-none">
                {profile.age}
              </span>
            )}
            {profile.is_verified && <VerifiedBadge size={18} />}
            {profile.is_online && (
              <span className="flex items-center gap-1.5 text-[12px] text-white/85">
                <span
                  className="w-2 h-2 rounded-full bg-[#4ade80] shadow-[0_0_6px_#4ade80]"
                  aria-hidden="true"
                />
                в сети
              </span>
            )}
          </div>
        </div>
      </div>

      {/* ── Текстовая часть ────────────────────────────────────── */}
      <div className="px-5 pt-4 pb-8">
        {(profile.city || profile.height_cm != null) && (
          <div className="flex items-center gap-3 text-[13.5px] text-text-secondary mb-3">
            {profile.city && (
              <span className="flex items-center gap-1.5 min-w-0">
                <MapPin size={14} className="shrink-0 text-text-muted" />
                <span className="truncate">{profile.city}</span>
              </span>
            )}
            {profile.height_cm != null && (
              <span className="flex items-center gap-1.5 shrink-0">
                <Ruler size={14} className="text-text-muted" />
                {profile.height_cm} см
              </span>
            )}
          </div>
        )}

        {/* Сообщение, приложенное к лайку, — ради него профиль и открыли */}
        {profile.like_message && (
          <blockquote
            className="mb-4 px-3.5 py-2.5 rounded-[var(--radius-tile)]
                       bg-accent/8 border border-accent/25 text-[14px] leading-snug"
          >
            «{profile.like_message}»
          </blockquote>
        )}

        {чипы.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-4">
            {чипы.map((label) => (
              <span
                key={label}
                className="text-[13px] px-3 py-1.5 rounded-full bg-surface-2
                           border border-hairline font-medium"
              >
                {label}
              </span>
            ))}
          </div>
        )}

        {profile.bio && (
          <section className="mb-4">
            <h3 className="text-[12px] font-semibold uppercase tracking-wide text-text-muted mb-1.5">
              О себе
            </h3>
            <p className="text-[15px] leading-relaxed whitespace-pre-wrap">
              {profile.bio}
            </p>
          </section>
        )}

        {profile.interests?.length > 0 && (
          <section className="mb-4">
            <h3 className="text-[12px] font-semibold uppercase tracking-wide text-text-muted mb-1.5">
              Интересы
            </h3>
            <div className="flex flex-wrap gap-1.5">
              {profile.interests.map((interest) => (
                <span
                  key={interest}
                  className="text-[13px] px-3 py-1.5 rounded-full bg-surface-2
                             border border-hairline font-medium"
                >
                  {interest}
                </span>
              ))}
            </div>
          </section>
        )}

        {/* Сервер отдаёт канал только когда фича открыта владельцу анкеты —
            здесь просто собираем ссылку из username, как в шапке чата */}
        {profile.tg_channel && (
          <a
            href={`https://t.me/${profile.tg_channel}`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block text-[14px] text-accent hover:underline"
          >
            @{profile.tg_channel}
          </a>
        )}
      </div>

      {actions && (
        <div
          className="sticky bottom-0 px-5 pt-3 pb-6 safe-bottom
                     bg-gradient-to-t from-bg via-bg/90 to-transparent"
        >
          {actions}
        </div>
      )}
    </motion.div>
  );
}
