/**
 * Цитата ответа — в двух местах и с одним лицом: внутри пузыря и над полем
 * ввода. Разводить их на два вида значило бы показать человеку одно
 * сообщение дважды по-разному, и первый же ответ на кружок это выдаёт.
 *
 * Кружок в цитате показан кадром В СВОЕЙ ФОРМЕ, а не квадратиком: форму
 * выбирает отправитель, она часть сообщения, и без неё «ответ на звезду»
 * выглядит как ответ на пустоту — текста-то у видеосообщения нет.
 */

import { CornerUpLeft, X } from "lucide-react";
import type { MessageQuote as Цитата } from "../lib/api";
import { noteMaskStyle } from "../lib/noteShapes";
import { formatClock } from "./VoiceBubble";

/** Чем подписать цитату, у которой нет текста. */
function подпись(q: Цитата): string {
  if (q.text) return q.text;
  if (q.kind === "video_note") return `Видеосообщение · ${formatClock(q.duration)}`;
  if (q.kind === "voice") return `Голосовое · ${formatClock(q.duration)}`;
  if (q.kind === "reel") return "Ролик";
  if (q.kind === "photo") return "Фотография";
  return "Сообщение";
}

function Кадр({ q, size }: { q: Цитата; size: number }) {
  if (q.kind === "video_note" && q.poster) {
    return (
      <span
        className="shrink-0 block note-shape overflow-hidden"
        style={{ width: size, height: size, ...noteMaskStyle(q.shape) }}
      >
        <img src={q.poster} alt="" className="w-full h-full object-cover" />
      </span>
    );
  }
  if (q.image_url) {
    return (
      <img
        src={q.image_url}
        alt=""
        className="shrink-0 rounded-md object-cover"
        style={{ width: size, height: size }}
      />
    );
  }
  return null;
}

interface БлокProps {
  quote: Цитата;
  /** Имя автора цитаты — «Вы» или собеседник. */
  author: string;
  /** Пузырь свой: линия и текст берут его цвет, а не акцент темы. */
  mine: boolean;
  onJump?: () => void;
}

/** Цитата внутри пузыря ответа. */
export function QuoteBlock({ quote, author, mine, onJump }: БлокProps) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onJump?.();
      }}
      className="w-full flex items-center gap-2 mb-1.5 pl-2 pr-2 py-1
                 rounded-[10px] text-left overflow-hidden"
      style={{
        // Своя — светлее пузыря, чужая — темнее фона: в обоих случаях
        // цитата остаётся подложкой, а не вторым сообщением
        background: mine ? "rgba(255,255,255,0.16)" : "rgba(127,127,127,0.14)",
        boxShadow: `inset 2.5px 0 0 0 ${
          mine ? "rgba(255,255,255,0.7)" : "var(--color-accent)"
        }`,
      }}
    >
      <Кадр q={quote} size={30} />
      <span className="min-w-0 flex-1 block leading-tight py-[1px]">
        <span
          className="block text-[12px] font-semibold truncate"
          style={{ color: mine ? "inherit" : "var(--color-accent)" }}
        >
          {author}
        </span>
        <span className="block text-[12.5px] truncate opacity-75">
          {подпись(quote)}
        </span>
      </span>
    </button>
  );
}

interface ПолосаProps {
  quote: Цитата;
  author: string;
  onCancel: () => void;
  onJump?: () => void;
}

/** Полоса над полем ввода: на что отвечаем. */
export function ReplyStrip({ quote, author, onCancel, onJump }: ПолосаProps) {
  return (
    <div
      className="flex items-center gap-2 mb-2 pl-2 pr-1 py-1.5 rounded-[12px]
                 bg-surface-2 border border-hairline"
    >
      <CornerUpLeft size={16} className="shrink-0 text-accent ml-1" />
      <Кадр q={quote} size={30} />
      <button
        type="button"
        onClick={onJump}
        className="min-w-0 flex-1 text-left leading-tight"
      >
        <span className="block text-[12px] font-semibold text-accent truncate">
          Ответ · {author}
        </span>
        <span className="block text-[12.5px] text-text-secondary truncate">
          {подпись(quote)}
        </span>
      </button>
      <button
        type="button"
        aria-label="Отменить ответ"
        onClick={onCancel}
        className="shrink-0 w-9 h-9 rounded-full flex items-center justify-center
                   text-text-muted active:bg-surface transition-colors"
      >
        <X size={17} />
      </button>
    </div>
  );
}
