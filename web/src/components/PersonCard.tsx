/**
 * Стеклянная мини-карточка человека: фото на всю плитку, затемнение, имя с
 * возрастом и город — та же визуальная система, что у полноэкранной карточки
 * в деке (SwipeCard), в масштабе сетки.
 *
 * Один компонент на «кто лайкнул», «гости» и новые совпадения: списки людей
 * обязаны выглядеть одинаково везде, иначе каждый экран приходится учить
 * читать заново. Рамка из кейсов и наклейка рисуются и здесь — коллекция,
 * видная только в деке, вполовину дешевле.
 *
 * Компонент презентационный: без собственных кнопок. Действия (лайк, ответ,
 * письмо) кладут через children — вложенные интерактивы внутри «карточки-
 * кнопки» ломали бы и HTML, и читалки.
 */

import type { ReactNode } from "react";
import { MapPin } from "lucide-react";
import type { UserProfile } from "../lib/api";
import { letterAvatarStyle } from "../lib/aura";
import { decorStyle } from "../lib/decor";
import { VerifiedBadge } from "./ui";

interface Props {
  profile: UserProfile;
  /** Правый верхний угол — счётчик визитов, время, что угодно короткое. */
  badge?: ReactNode;
  /** Низ карточки под городом: сообщение лайка, кнопки действий. */
  children?: ReactNode;
  /** tile — сетка в 2 колонки; mini — горизонтальная лента поуже. */
  size?: "tile" | "mini";
  /** Сейчас в сети — зелёная точка, как в деке. */
  online?: boolean;
}

export default function PersonCard({
  profile,
  badge,
  children,
  size = "tile",
  online,
}: Props) {
  const decor = decorStyle(profile.decor);
  const mini = size === "mini";

  return (
    <article
      className="relative w-full aspect-[3/4] rounded-[var(--radius-tile)]
                 overflow-hidden bg-surface-2"
    >
      {profile.photos?.[0] ? (
        <img
          src={profile.photos[0]}
          alt={profile.display_name}
          loading="lazy"
          decoding="async"
          className="absolute inset-0 w-full h-full object-cover"
        />
      ) : (
        <div
          className={`absolute inset-0 flex items-center justify-center
                      font-bold opacity-90 ${mini ? "text-3xl" : "text-4xl"}`}
          style={letterAvatarStyle(profile.id)}
        >
          {profile.display_name?.[0]?.toUpperCase() ?? "?"}
        </div>
      )}

      <div className="absolute inset-0 bg-scrim pointer-events-none" />

      {/* Рамка из кейсов — поверх фото и затемнения, как в деке */}
      {decor && (
        <div
          aria-hidden="true"
          className="absolute inset-0 rounded-[inherit] pointer-events-none z-[15]"
          style={{ boxShadow: `${decor.ring}, ${decor.glow}` }}
        />
      )}

      {badge && <div className="absolute top-2 right-2 z-20">{badge}</div>}

      {/* Наклейка — средний значок в верхнем углу фото, как в деке. В строке
          имени она сжималась до пятна и толкала имя в многоточие */}
      {profile.sticker && (
        <img
          src={profile.sticker}
          alt=""
          draggable={false}
          className={`absolute z-20 -rotate-6 select-none
                      drop-shadow-[0_2px_6px_rgba(0,0,0,.55)] ${
                        mini ? "top-1.5 left-1.5 w-7 h-7" : "top-2 left-2 w-9 h-9"
                      }`}
        />
      )}

      <div className={`absolute inset-x-0 bottom-0 z-20 ${mini ? "p-2" : "p-3"}`}>
        <div className={`flex items-center min-w-0 ${mini ? "gap-1" : "gap-1.5"}`}>
          <span
            className={`text-white truncate ${
              mini
                ? "text-[14px] font-bold tracking-[-0.01em]"
                : "text-[17px] font-extrabold tracking-[-0.02em]"
            }`}
          >
            {profile.display_name}
          </span>
          {profile.age != null && (
            <span
              className={`font-light text-white/85 shrink-0 ${
                mini ? "text-[13px]" : "text-[15px]"
              }`}
            >
              {profile.age}
            </span>
          )}
          {profile.is_verified && <VerifiedBadge size={mini ? 12 : 14} />}
          {online && (
            <span
              role="img"
              aria-label="Сейчас в сети"
              className="shrink-0 w-2 h-2 rounded-full bg-[#4ade80] shadow-[0_0_6px_#4ade80]"
            />
          )}
        </div>

        {profile.city && (
          <div
            className={`flex items-center gap-1 text-white/75 mt-0.5 ${
              mini ? "text-[11px]" : "text-[12px]"
            }`}
          >
            <MapPin size={mini ? 10 : 12} className="shrink-0" />
            <span className="truncate">{profile.city}</span>
          </div>
        )}

        {children}
      </div>
    </article>
  );
}
