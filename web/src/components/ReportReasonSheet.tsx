/**
 * Выбор причины жалобы на единицу контента: ролик, историю, сообщение
 * комнаты, комментарий.
 *
 * App Store (Guideline 1.2, UGC) требует кнопку жалобы на каждой
 * поверхности с чужим контентом. Лист один на все поверхности — иначе
 * причины и формулировки разъезжаются, а модератор получает жалобы,
 * которые нельзя сравнивать между собой.
 *
 * Поверх всего (z-70): открывается и из просмотрщика историй (z-60), и из
 * шторки комментариев (z-50) — ниже он был бы просто не виден.
 */

import { AnimatePresence, motion } from "framer-motion";
import { REPORT_REASONS } from "../lib/profileOptions";
import { Button } from "./ui";

export default function ReportReasonSheet({
  open,
  title,
  subtitle,
  onClose,
  onPick,
}: {
  open: boolean;
  title: string;
  /** Что случится после жалобы — человек должен понимать, куда она уйдёт. */
  subtitle: string;
  onClose: () => void;
  onPick: (reason: string) => void;
}) {
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-[70] bg-black/60"
          />
          <motion.div
            role="dialog"
            aria-label="Причина жалобы"
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", stiffness: 380, damping: 36 }}
            className="fixed bottom-0 left-0 right-0 z-[71] bg-bg-elevated
                       rounded-t-[var(--radius-sheet)] border-t border-hairline
                       px-5 pt-3 pb-7 safe-bottom max-h-[80dvh]
                       overflow-y-auto no-scrollbar"
          >
            <div className="w-10 h-1 rounded-full bg-surface-3 mx-auto mb-5" />

            <h2 className="text-heading font-bold mb-1.5">{title}</h2>
            <p className="text-caption text-text-muted mb-4">{subtitle}</p>

            <div className="flex flex-col gap-1.5 mb-4">
              {REPORT_REASONS.map((r) => (
                <button
                  key={r.value}
                  onClick={() => onPick(r.value)}
                  className="w-full px-4 py-3 rounded-[var(--radius-tile)] text-left
                             bg-surface-2 border border-hairline text-[15px]
                             active:bg-surface transition-colors"
                >
                  {r.label}
                </button>
              ))}
            </div>

            <Button variant="secondary" size="lg" fullWidth onClick={onClose}>
              Отмена
            </Button>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
