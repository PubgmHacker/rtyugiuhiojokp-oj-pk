/**
 * Интро перед анкетой: настоящие экраны приложения в рамке телефона.
 *
 * Показывается один раз — новому человеку без черновика и без имени.
 * Никаких абстрактных иллюстраций: слайды — это скриншоты ленты, лайков,
 * чата и видео, снятые с реального интерфейса (public/onboarding/*.webp).
 * Так обещание и продукт совпадают с первого экрана.
 *
 * Слайды листаются сами каждые 3,4 с, пальцем в любую сторону и точками.
 * Автопрокрутка останавливается после первого касания и при
 * prefers-reduced-motion: человек, который читает медленно или которого
 * укачивает от движения, управляет сам.
 */
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { haptic } from "../lib/haptics";
import { Button } from "../components/ui";
import BrandMark from "./BrandMark";

interface Слайд {
  экран: string;
  заголовок: string;
  текст: string;
}

const СЛАЙДЫ: Слайд[] = [
  {
    экран: "discover",
    заголовок: "Анкеты, которые вам подходят",
    текст: "Лента учитывает интересы и цели, а не только фото.",
  },
  {
    экран: "likes",
    заголовок: "Кто вас лайкнул — видно сразу",
    текст: "Ответная симпатия открывает чат без ожидания.",
  },
  {
    экран: "chat",
    заголовок: "Разговор без пустого «привет»",
    текст: "Подсказки для первого сообщения и серии общения.",
  },
  {
    экран: "reels",
    заголовок: "Видео и истории",
    текст: "Покажите себя живьём: короткие ролики и истории на сутки.",
  },
];

const ИНТЕРВАЛ_МС = 3400;
const ПОРОГ_СВАЙПА = 56;

const src = (экран: string) => `/onboarding/${экран}.webp`;

export default function OnboardingIntro({ onStart }: { onStart: () => void }) {
  const [индекс, setИндекс] = useState(0);
  const [направление, setНаправление] = useState(1);
  // Автопрокрутка выключается навсегда после первого жеста: человек взял
  // управление — не отбираем
  const [авто, setАвто] = useState(true);
  const безДвижения = useReducedMotion();
  const таймер = useRef<number | null>(null);

  // Все экраны догружаем сразу: слайд без картинки — пустая рамка
  useEffect(() => {
    СЛАЙДЫ.forEach((с) => {
      const img = new Image();
      img.src = src(с.экран);
    });
  }, []);

  useEffect(() => {
    if (!авто || безДвижения) return;
    таймер.current = window.setTimeout(() => {
      setНаправление(1);
      setИндекс((i) => (i + 1) % СЛАЙДЫ.length);
    }, ИНТЕРВАЛ_МС);
    return () => {
      if (таймер.current) window.clearTimeout(таймер.current);
    };
  }, [индекс, авто, безДвижения]);

  const перейти = (к: number) => {
    setАвто(false);
    const след = (к + СЛАЙДЫ.length) % СЛАЙДЫ.length;
    setНаправление(след > индекс || (индекс === СЛАЙДЫ.length - 1 && след === 0) ? 1 : -1);
    setИндекс(след);
    haptic("light");
  };

  const слайд = СЛАЙДЫ[индекс];
  const сдвиг = безДвижения ? 0 : 36;

  return (
    <div className="flex flex-col h-screen-safe overflow-hidden">
      <header className="safe-top px-5 pt-3 shrink-0 flex items-center justify-between min-h-[44px]">
        <div className="flex items-center gap-2.5">
          <BrandMark size={28} />
          <span className="text-[17px] font-bold tracking-[-0.02em]">Симп</span>
        </div>
        <button
          onClick={() => {
            haptic("light");
            onStart();
          }}
          className="tap-target px-2 -mr-2 text-[15px] font-semibold text-text-muted"
        >
          Пропустить
        </button>
      </header>

      {/* Телефон. Свайп ловим на всей области, а не на картинке: палец
          редко попадает точно в рамку */}
      <motion.div
        role="group"
        aria-roledescription="карусель"
        aria-label={`Экран ${индекс + 1} из ${СЛАЙДЫ.length}`}
        className="relative flex-1 min-h-0 flex items-center justify-center px-8 pt-2 touch-pan-y"
        drag="x"
        dragConstraints={{ left: 0, right: 0 }}
        dragElastic={0.12}
        dragMomentum={false}
        onDragEnd={(_, info) => {
          if (info.offset.x < -ПОРОГ_СВАЙПА) перейти(индекс + 1);
          else if (info.offset.x > ПОРОГ_СВАЙПА) перейти(индекс - 1);
        }}
      >
        <div
          aria-hidden="true"
          className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2
                     w-[70vw] max-w-[320px] aspect-square rounded-full
                     bg-accent/25 blur-3xl"
        />
        <div className="relative w-[min(62vw,258px)]">
          <AnimatePresence mode="popLayout" custom={направление} initial={false}>
            <motion.div
              key={слайд.экран}
              custom={направление}
              initial={{ opacity: 0, x: сдвиг * направление, scale: 0.97 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: -сдвиг * направление, scale: 0.97 }}
              transition={{ type: "spring", stiffness: 300, damping: 30 }}
              className="onb-phone"
            >
              <img src={src(слайд.экран)} alt="" decoding="async" draggable={false} />
            </motion.div>
          </AnimatePresence>
        </div>
      </motion.div>

      {/* Текст фиксированной высоты: заголовки разной длины не должны
          дёргать точки и кнопку */}
      <div className="px-6 pt-5 shrink-0 min-h-[108px]">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={слайд.экран}
            initial={{ opacity: 0, y: безДвижения ? 0 : 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: безДвижения ? 0 : -6 }}
            transition={{ duration: 0.22 }}
            className="text-center"
          >
            <h1 className="text-[24px] leading-[1.15] font-extrabold tracking-[-0.02em]">
              {слайд.заголовок}
            </h1>
            <p className="mt-2 text-[15px] leading-snug text-text-muted">{слайд.текст}</p>
          </motion.div>
        </AnimatePresence>
      </div>

      <div className="flex justify-center gap-1.5 pt-4 shrink-0" role="tablist" aria-label="Экраны">
        {СЛАЙДЫ.map((с, i) => (
          <button
            key={с.экран}
            role="tab"
            aria-selected={i === индекс}
            aria-label={`Экран ${i + 1}`}
            onClick={() => перейти(i)}
            className="tap-target flex items-center justify-center px-0.5"
          >
            <span
              className={`block h-[6px] rounded-full transition-all duration-300 ${
                i === индекс ? "w-[22px] bg-accent" : "w-[6px] bg-text-faint/60"
              }`}
            />
          </button>
        ))}
      </div>

      <div className="px-5 pt-4 pb-5 safe-bottom shrink-0">
        <Button size="lg" fullWidth onClick={onStart} hapticKind="success">
          Начать
        </Button>
      </div>
    </div>
  );
}
