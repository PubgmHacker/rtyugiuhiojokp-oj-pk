/**
 * Нижний лист. Один примитив на все всплывающие панели приложения.
 *
 * Утягивание вниз обязательно: на телефоне это основной жест закрытия, и
 * лист, который закрывается только крестиком, воспринимается как ловушка.
 * Порог 90px или скорость 500 — по скорости закрывается короткий резкий
 * свайп, по расстоянию медленное перетаскивание.
 */
import { useEffect, useId, useRef } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { haptic } from "../lib/haptics";

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  subtitle?: string;
  children: React.ReactNode;
  /** Убрать крестик — когда закрытие только жестом. */
  bare?: boolean;
  maxHeight?: string;
}

export function Sheet({
  open,
  onClose,
  title,
  subtitle,
  children,
  bare = false,
  maxHeight = "82vh",
}: SheetProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();

  // Прокрутку за листом блокируем: под открытой панелью уезжающий фон
  // читается как сбой, а на iOS ещё и утягивает лист вместе с собой.
  // Фокус переводим в лист и возвращаем при закрытии: без этого клавиатура
  // и скринридер остаются на странице ПОД листом, а сам лист для них нем.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    const prevFocus = document.activeElement as HTMLElement | null;
    document.body.style.overflow = "hidden";
    panelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      // Tab не должен уводить фокус за пределы модального листа
      if (e.key === "Tab" && panelRef.current) {
        const focusables = panelRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (!focusables.length) {
          e.preventDefault();
          return;
        }
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        const active = document.activeElement;
        if (e.shiftKey && (active === first || active === panelRef.current)) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
      prevFocus?.focus?.();
    };
  }, [open, onClose]);

  const закрыть = () => {
    haptic("light");
    onClose();
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-end justify-center"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
        >
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-[2px]"
            onClick={закрыть}
          />

          <motion.div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={title ? titleId : undefined}
            tabIndex={-1}
            className="relative w-full max-w-lg overflow-hidden border-t border-hairline bg-bg-elevated pb-[max(env(safe-area-inset-bottom),16px)] outline-none"
            style={{ borderTopLeftRadius: 20, borderTopRightRadius: 20, maxHeight }}
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", stiffness: 420, damping: 38 }}
            drag="y"
            dragConstraints={{ top: 0, bottom: 0 }}
            dragElastic={{ top: 0, bottom: 0.6 }}
            onDragEnd={(_, info) => {
              if (info.offset.y > 90 || info.velocity.y > 500) закрыть();
            }}
          >
            {/* Полоска-ручка: показывает, что лист тянется, до первой попытки */}
            <div className="flex justify-center pt-2.5 pb-1">
              <div className="h-1 w-10 rounded-full bg-surface-3" />
            </div>

            {(title || !bare) && (
              <div className="flex items-start gap-3 px-5 pb-3">
                <div className="min-w-0 flex-1">
                  {title && (
                    <h2 id={titleId} className="text-[17px] font-semibold leading-tight text-text">
                      {title}
                    </h2>
                  )}
                  {subtitle && (
                    <p className="mt-0.5 text-[13px] leading-snug text-text-muted">
                      {subtitle}
                    </p>
                  )}
                </div>
                {!bare && (
                  <button
                    onClick={закрыть}
                    aria-label="Закрыть"
                    className="tap-target -mr-1 -mt-1 grid h-9 w-9 place-items-center rounded-full text-text-muted transition-colors active:bg-surface-2"
                  >
                    <X size={20} />
                  </button>
                )}
              </div>
            )}

            <div
              className="no-scrollbar overflow-y-auto overscroll-contain px-5 pb-2"
              style={{ maxHeight: `calc(${maxHeight} - 96px)` }}
            >
              {children}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
