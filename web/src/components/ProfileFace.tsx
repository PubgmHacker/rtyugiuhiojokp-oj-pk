/**
 * Лицо анкеты — как экран профиля в iOS-клиенте Plink.
 *
 * Обложка 212 на всю ширину, под ней амбиент того же цвета; аватар 112
 * висит на нижней кромке обложки и «прорезан» в ней настоящим вырезом
 * (маска-круг 126 с зазором в 7 px — так делает Discord, и так делает
 * Plink). Справа сверху — кисточка к обложкам, над аватаром — пузырь-мысль
 * с «о себе», под обложкой — тонированная кнопка «Изменить», имя с галочкой
 * и ролью. На этом лицо кончается.
 *
 * Карты счётчиков («2 Фото · 0 Видео · 3 Интереса») здесь нет намеренно. Это
 * своя анкета, а не чужая: хозяин и так знает, сколько у него фото, зато
 * прямо под лицом стоит карточка заполненности — она говорит о том же, но
 * по делу и со ссылкой. Рядом с ней три числа выглядели вторым, беззубым
 * упрёком, а «0 Видео» — крупным нулём в самом видном месте экрана.
 *
 * Цвет лица не зависит от темы приложения: кнопка, чип и бейджи берут
 * акцент обложки (пресет из кейсов или пара по id человека).
 */

import { Crown, Paintbrush, Pencil } from "lucide-react";
import type { UserProfile } from "../lib/api";
import { coverBackground, coverForProfile } from "../lib/cover";
import { letterAvatarStyle, readableOn } from "../lib/aura";
import { IdentityBadge } from "./ui";

/** Геометрия лица — цифры Plink (pt → px 1:1). */
export const ЛИЦО = {
  обложка: 212,
  аватар: 112,
  вырез: 126,
  нахлёст: 56,
  левый: 18,
} as const;

/** Сколько «о себе» помещается в пузырь целиком. Длиннее — обрезаем и
 *  показываем полный текст карточкой ниже. */
export const ПУЗЫРЬ_МАКС = 70;

/**
 * Нижняя кромка пузыря-мысли, от верха обложки.
 *
 * Пузырь прижат к этой линии и растёт вверх, а не вниз от неё: хвостики
 * висят у него под левым нижним углом, и при верхнем якоре они уезжали
 * вместе с текстом — у короткого «о себе» указывали в пустоту над головой,
 * у длинного упирались в наклейку. Прижатый низ держит их на одном месте —
 * на верхне-правой кромке аватара — при любой длине текста.
 */
const ПУЗЫРЬ_НИЗ = ЛИЦО.обложка - 12;

interface Props {
  profile: UserProfile;
  /** Своё лицо: кнопки «Изменить» и кисточка. Чужое — только смотреть. */
  own?: boolean;
  onEdit?: () => void;
  onDecor?: () => void;
  onBio?: () => void;
}

export default function ProfileFace({
  profile,
  own = false,
  onEdit,
  onDecor,
  onBio,
}: Props) {
  const cover = coverForProfile(profile);
  const photo = profile.photos?.[0];
  const cx = ЛИЦО.левый + ЛИЦО.аватар / 2;
  const cy = ЛИЦО.обложка + 2;
  const r = ЛИЦО.вырез / 2;
  // Маска вырезает круг из обложки: внутри — прозрачно, снаружи — обложка.
  // Полупиксель на границе — антиалиасинг, иначе кромка «зубчатая»
  const маска = `radial-gradient(circle ${r}px at ${cx}px ${cy}px, transparent ${r - 0.5}px, #000 ${r + 0.5}px)`;
  const тонированный = { "--tint": cover.accent } as React.CSSProperties;
  const bio = (profile.bio ?? "").trim();
  const мысль = bio.length > ПУЗЫРЬ_МАКС ? bio.slice(0, ПУЗЫРЬ_МАКС - 1).trimEnd() + "…" : bio;

  return (
    <section aria-label="Анкета" className="relative">
      {/* Амбиент: та же обложка, отражённая и размытая, светит из-под
          страницы — лицо не обрывается на кромке обложки */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 -top-10 h-[420px] opacity-55"
        style={{
          background: coverBackground(cover),
          transform: "scaleY(-1)",
          filter: "blur(70px)",
          maskImage: "linear-gradient(180deg, transparent 0%, #000 30%, #000 60%, transparent 100%)",
          WebkitMaskImage:
            "linear-gradient(180deg, transparent 0%, #000 30%, #000 60%, transparent 100%)",
        }}
      />

      {/* Обложка с вырезом */}
      <div
        className="relative"
        style={{
          height: ЛИЦО.обложка,
          background: coverBackground(cover),
          maskImage: маска,
          WebkitMaskImage: маска,
        }}
      >
        {own && onDecor && (
          <button
            type="button"
            onClick={onDecor}
            aria-label={`Обложка: ${cover.title}. Сменить`}
            /* Не glass-soft: он светлый и на светлой обложке кнопка
               исчезала. Тёмный скрим читается и на пастельном градиенте,
               и на фотографии — как элементы управления над фото в iOS. */
            className="absolute top-3 right-[14px] w-8 h-8 rounded-full
                       bg-black/35 backdrop-blur-md border border-white/25
                       shadow-[0_1px_6px_rgba(0,0,0,.35)]
                       flex items-center justify-center text-white active:scale-95 transition-transform"
          >
            <Paintbrush size={15} />
          </button>
        )}
      </div>

      {/* Аватар на кромке */}
      <div
        className="absolute"
        style={{ left: ЛИЦО.левый, top: ЛИЦО.обложка - ЛИЦО.нахлёст, width: ЛИЦО.аватар, height: ЛИЦО.аватар }}
      >
        <div className="w-full h-full rounded-full overflow-hidden bg-bg">
          {photo ? (
            <img src={photo} alt={profile.display_name} className="w-full h-full object-cover" draggable={false} />
          ) : (
            <div
              className="w-full h-full flex items-center justify-center text-[40px] font-bold text-white/90"
              style={letterAvatarStyle(profile.id)}
            >
              {profile.display_name?.[0]?.toUpperCase() ?? "?"}
            </div>
          )}
        </div>
        {profile.sticker && (
          <img
            src={profile.sticker}
            alt=""
            draggable={false}
            /* Низ, а не верх: сверху справа садятся хвостики пузыря-мысли, и
               наклейка их перекрывала — мысль оказывалась ничьей */
            className="absolute -bottom-1 -right-3 w-11 h-11 rotate-6 select-none
                       drop-shadow-[0_2px_6px_rgba(0,0,0,.5)]"
          />
        )}
      </div>

      {/* Пузырь-мысль над аватаром, хвостики к нему */}
      {(мысль || own) && (
        <button
          type="button"
          disabled={!own}
          onClick={onBio}
          className="status-bubble absolute max-w-[min(58%,236px)] text-left"
          style={{ left: ЛИЦО.левый + ЛИЦО.аватар - 6, top: ПУЗЫРЬ_НИЗ, transform: "translateY(-100%)" }}
          aria-label={мысль ? "О себе. Изменить" : "Добавить пару слов о себе"}
        >
          <span className={`block text-[13px] leading-snug ${мысль ? "" : "text-text-muted"}`}>
            {мысль || "Пара слов о себе…"}
          </span>
        </button>
      )}

      {/* Ряд под обложкой: справа кнопка, слева место аватару */}
      <div className="flex justify-end px-[14px]" style={{ minHeight: ЛИЦО.нахлёст + 6, paddingTop: 10 }}>
        {own && onEdit && (
          <button
            type="button"
            onClick={onEdit}
            style={тонированный}
            className="glass-tint h-[42px] px-4 rounded-[14px] flex items-center gap-2
                       text-[14px] font-semibold active:scale-[0.97] transition-transform"
          >
            <Pencil size={15} />
            Изменить
          </button>
        )}
      </div>

      {/* Имя, роль, возраст и город */}
      <div className="px-[18px] pt-1">
        <div className="flex items-center gap-2 min-w-0">
          <h1 className="text-[22px] font-extrabold tracking-[-0.02em] truncate">
            {profile.display_name || "Без имени"}
          </h1>
          <IdentityBadge profile={profile} size={19} />
          {profile.is_premium && (
            <span
              /* Цвет буквы считаем от акцента: на «Заре» и «Затмении» чёрный
                 текст верен, а на синей паре личности он почти не виден */
              className="shrink-0 inline-flex items-center gap-1 px-2 h-[18px] rounded-full
                         text-[10px] font-black tracking-[0.05em]"
              style={{ background: cover.accent, color: readableOn(cover.accent) }}
            >
              <Crown size={9} fill="currentColor" />
              PREMIUM
            </span>
          )}
        </div>
        <p className="text-text-muted text-[14px] mt-0.5">
          {profile.age ? `${profile.age} · ` : ""}
          {profile.city || "Город не указан"}
        </p>
      </div>
    </section>
  );
}
