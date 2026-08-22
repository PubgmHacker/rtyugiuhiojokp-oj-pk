/**
 * Шторка суточного лимита бесплатного уровня — лайки и открытие мэтчей.
 *
 * Одна на оба лимита: тексты разные, а разговор один и тот же — «на сегодня
 * всё, дальше по подписке или до возврата слота». Двумя компонентами это
 * разъехалось бы в формулировках ровно там, где человек решает платить.
 *
 * Время возврата показываем настоящее, из `*_reset_at`: окно скользящее (24
 * часа с первого израсходованного слота), и «завтра в полночь» было бы
 * неправдой. Сервер считает это окно сам — клиент только показывает.
 */
import { Link } from "react-router-dom";
import { Crown, Heart, MessageSquareLock } from "lucide-react";
import { Sheet } from "./Sheet";
import { Button } from "./ui";
import { haptic } from "../lib/haptics";
import { useЯзык, перевести, форматВремени, форматДаты, type Язык } from "../lib/i18n";
import type { DailyLimits } from "../lib/api";

export type LimitKind = "likes" | "matches";

const ТЕКСТЫ: Record<
  LimitKind,
  { заголовок: string; описание: (лимит: number) => string }
> = {
  likes: {
    заголовок: "Лайки на сегодня закончились",
    описание: (лимит) =>
      `На бесплатном уровне ${лимит} ${падеж(лимит, "лайк", "лайка", "лайков")} в сутки. ` +
      "Смотреть анкеты можно дальше — пропуск лимит не тратит.",
  },
  matches: {
    заголовок: "Больше мэтчей — по подписке",
    описание: (лимит) =>
      `На бесплатном уровне открыто ${лимит} ${падеж(лимит, "мэтч", "мэтча", "мэтчей")} в сутки. ` +
      "Уже открытые остаются доступны — их можно читать и отвечать без ограничений.",
  },
};

export default function LimitSheet({
  kind,
  limits,
  open,
  onClose,
}: {
  kind: LimitKind;
  /** null — остатки не успели загрузиться; шторка всё равно объясняет суть. */
  limits: DailyLimits | null;
  open: boolean;
  onClose: () => void;
}) {
  const тексты = ТЕКСТЫ[kind];
  const язык = useЯзык();
  const лимит = kind === "likes" ? limits?.likes_total : limits?.matches_total;
  const сброс = kind === "likes" ? limits?.likes_reset_at : limits?.matches_reset_at;
  const Значок = kind === "likes" ? Heart : MessageSquareLock;

  return (
    <Sheet open={open} onClose={onClose} title={тексты.заголовок}>
      <div className="flex items-start gap-3 mb-4">
        <span
          className="w-10 h-10 rounded-full bg-accent/12 flex items-center
                     justify-center shrink-0"
        >
          <Значок size={19} className="text-accent" />
        </span>
        <p className="text-[14px] leading-snug text-text-secondary">
          {тексты.описание(лимит && лимит > 0 ? лимит : kind === "likes" ? 10 : 3)}
        </p>
      </div>

      {/* Точное время возврата, а не «попробуйте позже»: слот возвращается
          через 24 часа после того, как был потрачен */}
      {сброс && (
        <p className="text-caption text-text-muted mb-4">
          Следующий слот вернётся {когдаСлот(сброс, язык)}.
        </p>
      )}

      <Link to="/plans" onClick={() => haptic("light")} className="block mb-2.5">
        <Button size="lg" fullWidth>
          <Crown size={17} />
          Открыть без лимитов
        </Button>
      </Link>

      <Button variant="secondary" size="lg" fullWidth onClick={onClose}>
        Подожду до завтра
      </Button>
    </Sheet>
  );
}

/**
 * «сегодня в 21:40» / «завтра в 09:15» — время локальное, как у человека.
 *
 * Экспортируется: тот же текст показывает закрытый чат (pages/Chat.tsx), и
 * две копии формата разъехались бы — одна сказала бы «завтра», другая дату.
 *
 * Язык передаётся, а не читается из store: функция модульная, хуки здесь
 * недоступны, а вызывают её компоненты, у которых язык уже есть.
 */
export function когдаСлот(iso: string, язык: Язык): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return перевести(язык, "slot.withinDay");

  const время = форматВремени(d, язык);
  const сегодня = new Date();
  if (d.toDateString() === сегодня.toDateString())
    return перевести(язык, "slot.today", { time: время });

  const завтра = new Date(сегодня);
  завтра.setDate(сегодня.getDate() + 1);
  if (d.toDateString() === завтра.toDateString())
    return перевести(язык, "slot.tomorrow", { time: время });

  return перевести(язык, "slot.onDate", { date: форматДаты(d, язык), time: время });
}

function падеж(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}
