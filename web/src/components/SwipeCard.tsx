import {
  useState,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  memo,
} from "react";
import {
  motion,
  useMotionValue,
  useTransform,
  useMotionTemplate,
  type PanInfo,
  type MotionValue,
} from "framer-motion";
import { ChevronRight, Flag, MapPin, Sparkles } from "lucide-react";
import type { DeckProfile } from "../lib/api";
import { letterAvatarStyle } from "../lib/aura";
import { haptic } from "../lib/haptics";
import { IdentityBadge } from "./ui";
import { GOALS, RELATION_TYPES, SUBCULTURES, optionLabel } from "../lib/profileOptions";
import { decorStyle } from "../lib/decor";

export type SwipeDirection = "left" | "right" | "up";

interface SwipeCardProps {
  profile: DeckProfile;
  onSwipe: (direction: SwipeDirection, profile: DeckProfile) => void;
  isTop: boolean;
  index: number;
  /** Пожаловаться/заблокировать прямо с карточки — обязательная точка входа
   *  безопасности на поверхности, где человек видит незнакомца (App Store 1.2). */
  onFlag?: (profile: DeckProfile) => void;
  /** Открыть полную анкету: карточка показывает столько меток, сколько влезло
   *  в одну строку, а весь список живёт в шторке профиля. */
  onOpenProfile?: (profile: DeckProfile) => void;
}

/** Порог смещения и скорости, после которого жест считается свайпом. */
const OFFSET_THRESHOLD = 92;
const VELOCITY_THRESHOLD = 420;

/** Пружина, близкая к отклику нативного iOS. */
const SPRING = { type: "spring" as const, stiffness: 380, damping: 34, mass: 0.9 };

function SwipeCardImpl({
  profile,
  onSwipe,
  isTop,
  index,
  onFlag,
  onOpenProfile,
}: SwipeCardProps) {
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
  // Кайма по краю, а не заливка всей карточки: эффект не имеет права лежать
  // на фото пользователя (PRD §1.3, правило Z) — подсвечиваем рамку.
  const glowShadow = useMotionTemplate`inset 0 0 0 3px ${glowColor}, inset 0 0 34px -22px ${glowColor}`;

  const photos = profile.photos?.length ? profile.photos : [];
  // Видео анкеты листаются после фото тем же жестом. API наружу отдаёт
  // только публичные URL, но file_id бота на всякий случай не играем
  const videos = (profile.videos ?? []).filter((v) => /^https?:\/\//.test(v));
  const media = [
    ...photos.map((src) => ({ src, video: false })),
    ...videos.map((src) => ({ src, video: true })),
  ];
  const hasPhotos = photos.length > 0;
  const decor = decorStyle(profile.decor);

  // Порядок меток — по убыванию важности для решения: с кем и зачем,
  // потом «свой круг», тип и уже интересы. Что не влезло в строку,
  // прячется за «ещё N» и открывается в анкете
  const метки = useMemo(() => {
    const список = [
      profile.relation_type && optionLabel(RELATION_TYPES, profile.relation_type),
      profile.goal && optionLabel(GOALS, profile.goal),
      profile.subculture && optionLabel(SUBCULTURES, profile.subculture),
      // MBTI показываем кодом: расшифровка «INFJ · Активист» в тесную
      // карточку не влезает, а тем, кто ищет по типу, кода достаточно
      profile.mbti,
      ...(profile.interests ?? []),
    ].filter((x): x is string => !!x);
    // Интерес может повторить субкультуру («аниме») — второй раз не рисуем
    return Array.from(new Set(список));
  }, [
    profile.relation_type,
    profile.goal,
    profile.subculture,
    profile.mbti,
    profile.interests,
  ]);

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
      if (next < 0 || next >= media.length || next === photoIndex) return;
      haptic("select");
      setPhotoIndex(next);
    },
    [photoIndex, media.length]
  );

  // Прогреваем только ближайшие два фото. Полный прогрев галереи на каждой
  // карточке съедал мобильный канал: пять быстрых свайпов запускали десятки
  // загрузок, которые уже никому не нужны. Храним объекты до cleanup, чтобы
  // прервать незавершённые запросы при уходе карточки из стека.
  useEffect(() => {
    if (!isTop || photos.length < 2) return;
    const pending: HTMLImageElement[] = [];
    photos.slice(photoIndex + 1, photoIndex + 3).forEach((src) => {
      const img = new Image();
      img.decoding = "async";
      img.src = src;
      pending.push(img);
    });
    return () => {
      pending.forEach((img) => {
        img.src = "";
      });
    };
  }, [isTop, photos, photoIndex]);

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

  const current = media[photoIndex];

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

      {/* Фото или видео */}
      {current ? (
        <>
          {!loadedPhotos[photoIndex] && <div className="absolute inset-0 skeleton" />}
          {current.video ? (
            // Без звука и с автоплеем: карточка — витрина, не плеер.
            // playsInline обязателен, иначе iOS разворачивает на весь экран
            <video
              key={current.src}
              src={current.src}
              autoPlay
              muted
              loop
              playsInline
              onLoadedData={() =>
                setLoadedPhotos((m) => ({ ...m, [photoIndex]: true }))
              }
              className="w-full h-full object-cover pointer-events-none select-none"
            />
          ) : (
            <img
              key={current.src}
              src={current.src}
              alt={profile.display_name}
              onLoad={() => setLoadedPhotos((m) => ({ ...m, [photoIndex]: true }))}
              className="w-full h-full object-cover pointer-events-none select-none"
              draggable={false}
              decoding="async"
            />
          )}
        </>
      ) : (
        <div
          className="w-full h-full flex items-center justify-center"
          style={letterAvatarStyle(profile.id)}
        >
          <span className="text-[64px] font-extrabold opacity-90">
            {profile.display_name?.[0]?.toUpperCase() ?? "?"}
          </span>
        </div>
      )}

      {/* Затемнение под текстом */}
      <div className="absolute inset-0 bg-scrim pointer-events-none" />

      {/* Рамка коллекции. Над затемнением, но под индикатором фото и
          кнопками: свечение должно лежать на фото, а не перекрывать
          элементы, по которым нажимают */}
      {decor && (
        <div
          aria-hidden="true"
          className="absolute inset-0 rounded-[inherit] pointer-events-none z-[15]"
          style={{ boxShadow: `${decor.ring}, ${decor.glow}` }}
        />
      )}

      {/* Индикатор фото и видео + зоны перелистывания */}
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

      {/* Жалоба/блокировка — всегда доступна с карточки незнакомца.
          Гасим pointerdown до жеста: кнопка не должна начинать drag.
          Стекло тёмное (liquid-photo-quiet), а не общее светлое: на кадре
          со светлым фоном белая заливка подсвечивалась и служебная кнопка
          перебивала и бейдж совпадения, и само лицо. */}
      {isTop && onFlag && (
        <button
          aria-label={`Пожаловаться на ${profile.display_name}`}
          onPointerDownCapture={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation();
            haptic("light");
            onFlag(profile);
          }}
          className="absolute top-7 right-3 z-30 grid h-[34px] w-[34px] place-items-center
                     rounded-full liquid liquid-photo-quiet text-white/85 active:text-white
                     transition-colors after:absolute after:-inset-1.5 after:content-['']"
        >
          <Flag size={15} />
        </button>
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

      {/* Информация о профиле. Кнопки решений ушли под карточку, поэтому
          блок держит всю ширину — резерв справа больше не нужен */}
      <div className="absolute bottom-0 left-0 right-0 p-5 pb-6 z-20 pointer-events-none">
        {/* Слева имя и город, справа — наклейка из кейса: она занимает пустой
            угол над строкой меток, где раньше ничего не было. Одна и
            «наклеена» косо, как на крышку ноутбука: оформление анкеты, а не
            ещё одна иконка в строке. Витрина всех наклеек отвлекала бы от
            человека */}
        <div className="flex items-end gap-3">
          <div className="min-w-0 flex-1">
            {profile.match_score != null && (
              <div className="inline-flex items-center gap-1.5 mb-3 px-2.5 py-1 rounded-full liquid liquid-photo">
                <Sparkles size={13} className="text-accent-soft" />
                <span className="text-[12px] font-semibold">
                  Совпадение {profile.match_score}%
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
              {/* Галочка живой проверки: человек в анкете — реальный.
                  «В сети» незнакомцу не показываем: по нему можно следить за
                  чужим расписанием; статус остаётся только внутри мэтча */}
              <IdentityBadge profile={profile} size={20} />
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
          </div>

          {profile.sticker && (
            <img
              src={profile.sticker}
              alt=""
              draggable={false}
              className="block w-[68px] h-[68px] shrink-0 mb-2 -rotate-6 select-none
                         drop-shadow-[0_4px_10px_rgba(0,0,0,.55)]"
            />
          )}
        </div>

        {profile.bio && (
          <p className="text-[14px] leading-snug text-white/90 line-clamp-2 mb-2.5">
            {profile.bio}
          </p>
        )}

        {/* Одна строка меток вместо двух блоков с переносами: сколько влезло,
            столько и показываем, остальное — за «ещё N» */}
        {метки.length > 0 && (
          <ОдинРяд метки={метки} onMore={() => onOpenProfile?.(profile)} />
        )}
      </div>
    </motion.div>
  );
}

/* ── Метки анкеты в одну строку ─────────────────────────────── */

/** Зазор между метками — тот же, что был у flex-wrap (gap-1.5). */
const ЗАЗОР = 6;
/** Ширина, которую держим в резерве под кнопку «ещё N», px.
 *  Считана по верхней границе: «ещё 99» на 12px полужирном, плюс padding
 *  и шеврон. Занизить нельзя — тогда кнопка ужмёт строку и срежет метку. */
const РЕЗЕРВ = 76;

/**
 * Тип связи, цель, субкультура, MBTI и интересы — одной строкой.
 *
 * Двумя блоками с flex-wrap это превращалось в кашу: у человека с
 * субкультурой и десятком интересов плашки занимали треть карточки и
 * закрывали фото. Теперь в строку входит ровно столько меток, сколько
 * влезает по ширине, а хвост сворачивается в «ещё N» — она открывает
 * анкету, где список показан целиком.
 *
 * Ширины снимаем один раз, пока в DOM ещё весь набор, и держим в ref:
 * пересчёт по ResizeObserver идёт по сохранённым числам, поэтому строка
 * не мигает и не зацикливается на самой себе.
 */
function ОдинРяд({
  метки,
  onMore,
}: {
  метки: string[];
  onMore?: () => void;
}) {
  // Два узла: внешний держит всю доступную ширину (по нему считаем),
  // внутренний ужимается по содержимому — иначе кнопка «ещё N» улетала
  // к правому краю и повисала в пустоте
  const ряд = useRef<HTMLDivElement>(null);
  const коробка = useRef<HTMLDivElement>(null);
  const ширины = useRef<number[]>([]);
  const [влезло, setВлезло] = useState(метки.length);
  const ключ = метки.join("|");

  useLayoutEffect(() => {
    const box = ряд.current;
    const внутри = коробка.current;
    if (!box || !внутри) return;
    // Снимаем ширины только с полного набора: после сворачивания в DOM
    // остаётся хвост, и мерить по нему нечего
    if (ширины.current.length !== метки.length) {
      ширины.current = Array.from(внутри.children).map(
        (el) => (el as HTMLElement).offsetWidth
      );
    }

    const считать = () => {
      const доступно = box.clientWidth;
      // jsdom и скрытая карточка отдают ноль — тогда показываем всё
      if (!доступно) return;
      const влез = (лимит: number) => {
        let сумма = 0;
        let n = 0;
        for (const ш of ширины.current) {
          const шаг = сумма + (n ? ЗАЗОР : 0) + ш;
          if (шаг > лимит) break;
          сумма = шаг;
          n += 1;
        }
        return n;
      };
      let n = влез(доступно);
      if (n < ширины.current.length) n = влез(доступно - ЗАЗОР - РЕЗЕРВ);
      // Хотя бы одна метка: пустая строка выглядит как обрыв вёрстки
      setВлезло(Math.max(1, n));
    };

    считать();
    if (typeof ResizeObserver === "undefined") return;
    const наблюдатель = new ResizeObserver(считать);
    наблюдатель.observe(box);
    return () => наблюдатель.disconnect();
    // ключ, а не сам массив: у него новая ссылка на каждый рендер
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ключ]);

  const скрыто = метки.length - влезло;

  return (
    <div ref={ряд} className="flex items-center gap-1.5">
      <div ref={коробка} className="flex min-w-0 gap-1.5 overflow-hidden">
        {метки.slice(0, влезло).map((метка) => (
          <span
            key={метка}
            className="shrink-0 text-[12px] px-2.5 py-1 rounded-full liquid liquid-photo font-medium"
          >
            {метка}
          </span>
        ))}
      </div>
      {скрыто > 0 && (
        <button
          type="button"
          aria-label={`Ещё ${скрыто} — открыть анкету`}
          onPointerDownCapture={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation();
            haptic("light");
            onMore?.();
          }}
          className="shrink-0 pointer-events-auto inline-flex items-center gap-0.5
                     text-[12px] pl-2.5 pr-1.5 py-1 rounded-full liquid liquid-photo
                     font-semibold text-white/90 active:text-white transition-colors"
        >
          {/* Шеврон отличает кнопку от соседних плашек: без него «ещё 4»
              читается как ещё один факт анкеты, а не как вход в неё */}
          ещё {скрыто}
          <ChevronRight size={13} className="opacity-70" />
        </button>
      )}
    </div>
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
