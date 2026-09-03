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

      <Section title="Знакомства" items={DATING} />
      <Section title="Развлечения" items={FUN} />

      {/* Подписка внизу: покупка — редкое действие, наверху она выглядела бы
          навязчиво, но и прятать её незачем */}
      <section className="px-4 pt-5">
        <Link
          to="/plans"
          onClick={() => haptic("light")}
          className="glass-tint flex items-center gap-3 px-[14px] py-3 rounded-[20px]
                     active:scale-[0.99] transition-transform"
        >
          <span className="settings-badge">
            <Crown size={15} />
          </span>
          <div className="flex-1 min-w-0">
            <p className="font-semibold text-[15px]">Plus и Ultra</p>
            <p className="text-[12px] text-text-muted">
              Кто вас лайкнул, инкогнито, буст
            </p>
          </div>
          <ChevronRight size={14} className="text-text-faint shrink-0" />
        </Link>
      </section>
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
