/**
 * Ряд реакций под сообщением — как в Telegram, а не значком на углу пузыря.
 *
 * В личке собеседников двое, поэтому у ключа бывает 1 или 2 автора. Значок
 * на углу (путь iMessage) при двух разных реакциях начинает лепиться сам на
 * себя, а ряд плашек под сообщением остаётся читаемым и при шести.
 *
 * Своя плашка подсвечена тоном знака, а не общим акцентом: так видно, что
 * поставил именно ты, и не приходится вспоминать, какого цвета акцент темы.
 * Повторный тап по своей плашке снимает реакцию — это ожидание из всех
 * мессенджеров, отдельного крестика тут нет.
 */

import { motion, AnimatePresence } from "framer-motion";
import type { MessageReaction } from "../lib/api";
import {
  ReactionGlyph,
  REACTION_TINTS,
  REACTION_TITLES,
  isReactionKey,
} from "../lib/reactions";

interface Props {
  reactions: MessageReaction[] | null | undefined;
  myId: string | undefined;
  mine: boolean;
  onToggle: (key: string) => void;
}

export default function ReactionRow({ reactions, myId, mine, onToggle }: Props) {
  const видимые = (reactions ?? []).filter(
    (r) => isReactionKey(r.key) && r.users.length > 0
  );
  if (видимые.length === 0) return null;

  return (
    <div
      className={`flex flex-wrap gap-1 px-0.5 ${
        mine ? "justify-end" : "justify-start"
      }`}
    >
      <AnimatePresence initial={false}>
        {видимые.map((r) => {
          const моя = !!myId && r.users.includes(myId);
          const тон = REACTION_TINTS[r.key as keyof typeof REACTION_TINTS];
          return (
            <motion.button
              key={r.key}
              layout
              initial={{ opacity: 0, scale: 0.6 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.6 }}
              transition={{ type: "spring", stiffness: 520, damping: 30 }}
              onClick={() => onToggle(r.key)}
              aria-pressed={моя}
              aria-label={`${REACTION_TITLES[r.key as keyof typeof REACTION_TITLES]}${
                r.users.length > 1 ? `, ${r.users.length}` : ""
              }${моя ? ", ваша" : ""}`}
              className={`inline-flex items-center h-[24px] rounded-full
                          text-[12px] font-semibold tabular-nums
                          active:scale-95 transition-transform ${
                            r.users.length > 1 ? "gap-1 pl-1.5 pr-2" : "px-1.5"
                          }`}
              style={{
                // Чужая плашка — стекло, а не плоская поверхность: она лежит
                // на обоях переписки, и сплошная заливка читалась бы серым
                // пятном, наклеенным сверху.
                background: моя
                  ? `${тон}2e`
                  : "color-mix(in srgb, var(--color-surface-2) 78%, transparent)",
                backdropFilter: моя ? undefined : "blur(10px) saturate(150%)",
                WebkitBackdropFilter: моя ? undefined : "blur(10px) saturate(150%)",
                boxShadow: моя
                  ? `inset 0 0 0 1px ${тон}59`
                  : "inset 0 0 0 1px var(--color-hairline)",
                color: моя ? тон : "var(--color-text-secondary)",
              }}
            >
              <ReactionGlyph k={r.key as any} size={15} />
              {r.users.length > 1 && r.users.length}
            </motion.button>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
