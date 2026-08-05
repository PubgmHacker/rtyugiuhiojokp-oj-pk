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
  Mic,
  Sparkles,
  Star,
  Trophy,
  Users,
} from "lucide-react";
import { haptic } from "../lib/haptics";
import { ScreenHeader } from "../components/ui";

interface Item {
  path: string;
  icon: typeof Film;
  title: string;
  hint: string;
  /** Метка «за подписку» — чтобы не вести человека в тупик. */
  paid?: boolean;
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
    path: "/photo-ratings",
    icon: Star,
    title: "Оценка фото",
    hint: "Оцените чужие и узнайте оценку своего",
  },
  {
    path: "/likes",
    icon: Trophy,
    title: "Топ недели",
    hint: "Кто собрал больше лайков",
  },
  {
    path: "/cases",
    icon: Gift,
    title: "Кейсы",
    hint: "Суперлайки и буст по подписке",
    paid: true,
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
      <div className="px-4 pt-2">
        <Link
          to="/plans"
          onClick={() => haptic("light")}
          className="flex items-center gap-3 px-4 py-3.5 rounded-[var(--radius-tile)]
                     border border-accent/25 bg-accent/8"
        >
          <Crown size={19} className="text-accent shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="font-bold text-[15px]">Plus и Ultra</p>
            <p className="text-caption text-text-muted">
              Кто вас лайкнул, инкогнито, буст
            </p>
          </div>
          <ChevronRight size={18} className="text-text-faint shrink-0" />
        </Link>
      </div>
    </div>
  );
}

function Section({ title, items }: { title: string; items: Item[] }) {
  return (
    <section className="px-4 pt-4">
      <h2 className="text-caption text-text-muted mb-2.5 px-1">{title}</h2>
      <div className="flex flex-col gap-2">
        {items.map((item) => (
          <Link
            key={item.path}
            to={item.path}
            onClick={() => haptic("light")}
            className="flex items-center gap-3 px-4 py-3.5 rounded-[var(--radius-tile)]
                       bg-surface-2 border border-hairline
                       active:scale-[0.99] transition-transform"
          >
            <item.icon size={19} className="text-accent shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <p className="font-semibold text-[15px]">{item.title}</p>
                {item.paid && (
                  <Sparkles size={12} className="text-accent shrink-0" />
                )}
              </div>
              <p className="text-caption text-text-muted">{item.hint}</p>
            </div>
            <ChevronRight size={17} className="text-text-faint shrink-0" />
          </Link>
        ))}
      </div>
    </section>
  );
}
