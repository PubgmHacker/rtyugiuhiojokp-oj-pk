/**
 * «Ещё» — хаб дополнительных разделов.
 *
 * Пятая вкладка навигации, как в референсе. Разделов много, и каждому своя
 * вкладка не положена: в навигации помещается пять, а знакомства делаются в
 * первых трёх. Остальное живёт здесь.
 *
 * Порядок не случаен: сверху то, что помогает знакомиться (видео, комнаты),
 * ниже развлечения. Человеку в первый день нужны люди, а не лутбоксы.
 */

import { Link } from "react-router-dom";
import {
  ChevronRight,
  Crown,
  Film,
  Gift,
  ListChecks,
  Mic,
  Moon,
  Star,
  Trophy,
  Users,
} from "lucide-react";
import { haptic } from "../lib/haptics";
import { ScreenHeader } from "../components/ui";
import { SettingsGroup, SettingsRow } from "../components/SettingsRows";

interface Item {
  path: string;
  icon: typeof Film;
  title: string;
  hint: string;
  /** Платная фича: помечаем замком — это честно, а не «премиум-шильдик»,
      который звучит как реклама и который человек не попросил. */
  paid?: boolean;
  /** Премиум-класс: звезда рядом с иконкой, как в референсе — мягкий тизер
      подписки, а не стена, залитая акцентом целиком. */
  premium?: boolean;
}

/** Знакомства — то, что приводит к мэтчу. */
const DATING: Item[] = [
  {
    path: "/reels",
    icon: Film,
    title: "Видео",
    hint: "Короткие ролики — вас увидят живьём",
  },
  {
    path: "/rooms",
    icon: Users,
    title: "Чаты по интересам",
    hint: "Написать в общий чат проще, чем первым в личку",
  },
  {
    path: "/voice",
    icon: Mic,
    title: "Голосовая рулетка",
    hint: "Случайный голосовой звонок",
  },
];

/** Развлечения — поводы вернуться, но не способ познакомиться. */
const FUN: Item[] = [
  {
    path: "/habits",
    icon: ListChecks,
    title: "План дня",
    hint: "Задачи и привычки — прямо в чате",
  },
  {
    path: "/photo-ratings",
    icon: Star,
    title: "Оценка фото",
    hint: "Оцените чужие и узнайте оценку своего",
    premium: true,
  },
  {
    path: "/likes?tab=top",
    icon: Trophy,
    title: "Топ недели",
    hint: "Кто собрал больше лайков",
  },
  {
    path: "/cases",
    icon: Gift,
    title: "Кейсы",
    hint: "Наклейки и обложки для анкеты",
    paid: true,
  },
  {
    path: "/tarot",
    icon: Moon,
    title: "Карта дня",
    hint: "Карта дня и расклады — повод начать разговор",
    premium: true,
  },
];

export default function More() {
  return (
    <div className="pb-6">
      <ScreenHeader title="Ещё" />

      {/* Подписка первой строкой, как Telegram Premium в настройках: одна
          компактная карта под шапкой. Внизу списка она уезжала под таб-бар,
          и человек видел половину кнопки. */}
      <section className="px-4 pt-4">
        <Link
          to="/plans"
          onClick={() => haptic("light")}
          className="plans-hero relative flex items-center gap-3.5 px-4 py-3.5 rounded-[22px]
                     overflow-hidden active:scale-[0.99] transition-transform"
        >
          <span className="plans-hero-badge">
            <Crown size={18} strokeWidth={2} />
          </span>
          <div className="flex-1 min-w-0">
            <p className="font-bold text-[16px] tracking-[-0.01em]">Plus и Ultra</p>
            <p className="text-[13px] text-text-secondary leading-snug">
              Кто вас лайкнул, инкогнито и буст анкеты
            </p>
          </div>
          <ChevronRight size={16} className="text-text-faint shrink-0" />
        </Link>
      </section>

      <Section title="Знакомства" items={DATING} />
      <Section title="Развлечения" items={FUN} />
    </div>
  );
}

/** Секция по Plink: подпись капсом над стеклянной картой, строки внутри
 *  разделены волосяными линиями от значка, а не карточка на каждую. */
function Section({ title, items }: { title: string; items: Item[] }) {
  return (
    <SettingsGroup title={title} className="px-4 pt-5">
      {items.map((item) => (
        <SettingsRow
          key={item.path}
          to={item.path}
          icon={item.icon}
          title={item.title}
          hint={item.hint}
          premium={item.premium}
          locked={item.paid}
        />
      ))}
    </SettingsGroup>
  );
}
