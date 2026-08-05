/**
 * Карта дня — повод открыть приложение.
 *
 * Развлечение, а не предсказание: так и подписано. Расклад один на сутки,
 * поэтому закрытую карточку не показываем до следующего дня — иначе подсказка
 * мелькала бы на каждом открытии ленты и раздражала.
 */

import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Sparkles, X } from "lucide-react";
import { getDailyCard, recordSectionOpen, type DailyCard as Card } from "../lib/api";
import { haptic } from "../lib/haptics";

/** Ключ хранит дату последнего закрытия: сравниваем с сегодняшней. */
const DISMISSED_KEY = "sd_daily_card_dismissed";

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function DailyCardBanner() {
  const [card, setCard] = useState<Card | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (localStorage.getItem(DISMISSED_KEY) === today()) return;
    getDailyCard()
      .then(setCard)
      .catch(() => setCard(null)); // необязательная механика, молчим
  }, []);

  const dismiss = useCallback(() => {
    haptic("light");
    localStorage.setItem(DISMISSED_KEY, today());
    setCard(null);
  }, []);

  if (!card) return null;

  return (
    <div className="px-3 pb-2">
      <div
        className="rounded-[var(--radius-tile)] border border-accent/25 bg-accent/8
                   overflow-hidden"
      >
        <div className="flex items-center gap-2.5 px-3.5 py-2.5">
          <Sparkles size={16} className="text-accent shrink-0" />
          <button
            onClick={() => {
              haptic("light");
              // Считаем раскрытие, а не показ баннера: баннер видят все, кто
              // открыл ленту, и такая цифра ничего не сказала бы о разделе
              if (!open) recordSectionOpen("daily");
              setOpen((v) => !v);
            }}
            className="flex-1 text-left min-w-0"
          >
            <span className="text-[13.5px] font-semibold">
              {card.name} — {card.meaning}
            </span>
          </button>
          <button
            aria-label="Скрыть до завтра"
            onClick={dismiss}
            className="text-text-faint shrink-0"
          >
            <X size={16} />
          </button>
        </div>

        <AnimatePresence initial={false}>
          {open && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.18 }}
              className="overflow-hidden"
            >
              <div className="px-3.5 pb-3 pt-0">
                <p className="text-[13.5px] leading-snug text-text-secondary mb-1.5">
                  {card.advice}
                </p>
                <p className="text-[11.5px] text-text-faint">
                  Просто развлечение — не предсказание
                </p>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
