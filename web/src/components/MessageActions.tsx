/**
 * Панель длинного нажатия: ряд реакций и действия над сообщением.
 *
 * Панель привязана к самому сообщению, а не выезжает снизу экрана: шторка
 * снизу заставляет глаз уйти от того, на что нажали, и вернуться обратно —
 * на телефоне это полсекунды и потеря места в переписке. Здесь ряд встаёт
 * вплотную к пузырю с той же стороны, что и он.
 *
 * Под панелью лента уходит в расфокус, а само сообщение поднимается НАД
 * затемнением (MessageRow, свойство «поднято»): реакцию выбирают, глядя на
 * текст, и он обязан остаться резким. Без этого на тёмной теме затемнение
 * не видно вовсе — чёрное по чёрному, — и панель висит в воздухе.
 */

import { useEffect, useMemo } from "react";
import { motion } from "framer-motion";
import { CornerUpLeft, Copy, Video } from "lucide-react";
import {
  ReactionGlyph,
  REACTION_ORDER,
  REACTION_TINTS,
  REACTION_TITLES,
  type ReactionKey,
} from "../lib/reactions";

export interface Действие {
  key: string;
  label: string;
  icon: "reply" | "copy" | "note";
  danger?: boolean;
  onPick: () => void;
}

interface Props {
  anchor: DOMRect;
  mine: boolean;
  /** Мой текущий код на этом сообщении — подсвечен в ряду. */
  active: string | null;
  actions: Действие[];
  onPick: (key: ReactionKey) => void;
  onClose: () => void;
}

const ШАГ = 44;
const ВЫСОТА_РЯДА = 52;
const ЗАЗОР = 8;
const ПОЛЕ = 10;
const ШИРИНА_КАРТЫ = 208;

const ИКОНКИ = { reply: CornerUpLeft, copy: Copy, note: Video } as const;

export default function MessageActions({
  anchor,
  mine,
  active,
  actions,
  onPick,
  onClose,
}: Props) {
  // Прокрутка ленты увела бы панель от сообщения: пока она открыта, лента
  // стоит. Escape закрывает — панель ловит фокус клавиатуры целиком.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const место = useMemo(() => {
    const вш = window.innerWidth;
    const вв = window.innerHeight;
    const рядШ = REACTION_ORDER.length * ШАГ + 10;
    const картаВ = actions.length * 44 + 8;
    const всего = ВЫСОТА_РЯДА + ЗАЗОР + картаВ;

    const сверху = anchor.top - ЗАЗОР - всего >= ПОЛЕ;
    const top = сверху
      ? anchor.top - ЗАЗОР - всего
      : Math.min(anchor.bottom + ЗАЗОР, вв - всего - ПОЛЕ);

    const прижать = (ш: number) =>
      Math.max(ПОЛЕ, Math.min(mine ? anchor.right - ш : anchor.left, вш - ш - ПОЛЕ));

    return {
      top: Math.max(ПОЛЕ, top),
      рядLeft: прижать(рядШ),
      рядШ,
      картаTop: Math.max(ПОЛЕ, top) + ВЫСОТА_РЯДА + ЗАЗОР,
      картаLeft: прижать(ШИРИНА_КАРТЫ),
    };
  }, [anchor, mine, actions.length]);

  return (
    <>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.16 }}
        onClick={onClose}
        onContextMenu={(e) => {
          e.preventDefault();
          onClose();
        }}
        className="fixed inset-0 z-40 bg-black/45 backdrop-blur-[3px]"
      />

      {/* Ряд знаков */}
      <motion.div
        role="menu"
        aria-label="Реакция"
        initial={{ opacity: 0, scale: 0.86, y: 6 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.9, y: 4 }}
        transition={{ type: "spring", stiffness: 520, damping: 32 }}
        style={{
          top: место.top,
          left: место.рядLeft,
          width: место.рядШ,
          height: ВЫСОТА_РЯДА,
          transformOrigin: mine ? "bottom right" : "bottom left",
        }}
        className="fixed z-50 flex items-center justify-between px-[5px]
                   rounded-full bg-bg-elevated border border-hairline float-shadow"
      >
        {REACTION_ORDER.map((k, i) => (
          <motion.button
            key={k}
            role="menuitemradio"
            aria-checked={active === k}
            aria-label={REACTION_TITLES[k]}
            initial={{ opacity: 0, scale: 0.4 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{
              type: "spring",
              stiffness: 620,
              damping: 26,
              delay: 0.02 * i,
            }}
            onClick={() => onPick(k)}
            className="w-[42px] h-[42px] rounded-full flex items-center justify-center
                       active:scale-90 transition-transform"
            style={
              active === k
                ? { background: `${REACTION_TINTS[k]}24` }
                : undefined
            }
          >
            <ReactionGlyph k={k} size={22} />
          </motion.button>
        ))}
      </motion.div>

      {/* Действия */}
      <motion.div
        role="menu"
        aria-label="Действия с сообщением"
        initial={{ opacity: 0, y: -6, scale: 0.96 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, scale: 0.97 }}
        transition={{ type: "spring", stiffness: 460, damping: 32, delay: 0.04 }}
        style={{ top: место.картаTop, left: место.картаLeft, width: ШИРИНА_КАРТЫ }}
        className="fixed z-50 rounded-[var(--radius-tile)] overflow-hidden
                   bg-bg-elevated border border-hairline float-shadow"
      >
        {actions.map((д, i) => {
          const Icon = ИКОНКИ[д.icon];
          return (
            <button
              key={д.key}
              role="menuitem"
              onClick={д.onPick}
              className={`w-full h-11 flex items-center gap-2.5 px-4 text-left
                          text-[14.5px] active:bg-surface transition-colors ${
                            i ? "border-t border-hairline" : ""
                          } ${д.danger ? "text-danger" : ""}`}
            >
              <Icon size={16} className={д.danger ? "" : "text-text-muted"} />
              {д.label}
            </button>
          );
        })}
      </motion.div>
    </>
  );
}
