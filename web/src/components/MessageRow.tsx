/**
 * Оболочка одного сообщения: жест «потянуть вправо → ответить», долгое
 * нажатие на панель действий, ряд реакций под пузырём.
 *
 * Жест написан на pointer-событиях, а не на drag из framer: у голосового и
 * у кружка свои перетаскивания (перемотка), и универсальный drag забирал бы
 * палец у них. Поверхности перемотки помечены `data-scrub` — у полосы
 * голосового свайп не начинается вовсе, у кружка не начинается только с
 * внешней трети радиуса, где палец перематывает запись.
 *
 * Тянется сам пузырь: гап открывается слева от него, и в этот гап въезжает
 * стрелка — так это читается в Telegram, и переучивать людей не за чем.
 */

import { useCallback, useRef, useState, type PointerEvent, type ReactNode } from "react";
import { CornerUpLeft } from "lucide-react";
import type { ChatMessage } from "../lib/api";
import ReactionRow from "./ReactionRow";
import { haptic } from "../lib/haptics";

/** Дальше пузырь не едет: свободный сдвиг превращает ленту в качели. */
const ПОТОЛОК = 64;
/** С этого сдвига жест засчитан. */
const ПОРОГ = 44;
/** Долгое нажатие: ниже — срабатывает на обычном тапе, выше — залипает. */
const ДЕРЖАТЬ_МС = 380;

interface Props {
  m: ChatMessage;
  mine: boolean;
  myId: string | undefined;
  подсвечено: boolean;
  /** Открыта панель именно этого сообщения — оно встаёт над затемнением. */
  поднято?: boolean;
  onReply: (m: ChatMessage) => void;
  onMenu: (m: ChatMessage, rect: DOMRect) => void;
  onToggleReaction: (m: ChatMessage, key: string) => void;
  children: ReactNode;
}

/** Можно ли начинать жест из этой точки. */
function жестРазрешён(target: EventTarget | null, x: number, y: number): boolean {
  const узел = target instanceof Element ? target.closest("[data-scrub]") : null;
  if (!узел) return true;
  if (узел.getAttribute("data-scrub") !== "radial") return false;
  const r = узел.getBoundingClientRect();
  const dx = (x - (r.left + r.width / 2)) / (r.width / 2);
  const dy = (y - (r.top + r.height / 2)) / (r.height / 2);
  return Math.hypot(dx, dy) < 0.62;
}

export default function MessageRow({
  m,
  mine,
  myId,
  подсвечено,
  поднято,
  onReply,
  onMenu,
  onToggleReaction,
  children,
}: Props) {
  const [сдвиг, setСдвиг] = useState(0);
  const [тянем, setТянем] = useState(false);
  const старт = useRef<{ x: number; y: number; горизонт: boolean } | null>(null);
  const держим = useRef<ReturnType<typeof setTimeout> | null>(null);
  const съестьКлик = useRef(false);
  const корпус = useRef<HTMLDivElement>(null);

  const бросить = useCallback(() => {
    if (держим.current) {
      clearTimeout(держим.current);
      держим.current = null;
    }
  }, []);

  const вниз = (e: PointerEvent<HTMLDivElement>) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    if (!жестРазрешён(e.target, e.clientX, e.clientY)) return;
    старт.current = { x: e.clientX, y: e.clientY, горизонт: false };
    бросить();
    держим.current = setTimeout(() => {
      держим.current = null;
      старт.current = null;
      съестьКлик.current = true;
      setСдвиг(0);
      setТянем(false);
      haptic("medium");
      const box = корпус.current?.getBoundingClientRect();
      if (box) onMenu(m, box);
    }, ДЕРЖАТЬ_МС);
  };

  const движение = (e: PointerEvent<HTMLDivElement>) => {
    const s = старт.current;
    if (!s) return;
    const dx = e.clientX - s.x;
    const dy = e.clientY - s.y;
    if (Math.abs(dx) > 8 || Math.abs(dy) > 8) бросить();
    if (!s.горизонт) {
      // Вертикаль победила — это прокрутка ленты, жест снимаем
      if (Math.abs(dy) > 10 && Math.abs(dy) >= Math.abs(dx)) {
        старт.current = null;
        setТянем(false);
        setСдвиг(0);
        return;
      }
      if (dx < 12) return;
      s.горизонт = true;
      setТянем(true);
    }
    // Резина: у потолка палец проходит вчетверо больше, чем едет пузырь
    const сырой = Math.max(0, dx - 12);
    setСдвиг(сырой <= ПОТОЛОК ? сырой : ПОТОЛОК + (сырой - ПОТОЛОК) * 0.18);
  };

  const вверх = () => {
    бросить();
    const сработало = старт.current?.горизонт && сдвиг >= ПОРОГ;
    старт.current = null;
    setТянем(false);
    setСдвиг(0);
    if (сработало) {
      съестьКлик.current = true;
      onReply(m);
    }
  };

  return (
    <div
      id={`msg-${m.id}`}
      className={`relative w-full flex flex-col ${
        mine ? "items-end" : "items-start"
      }`}
      // z поверх затемнения панели (z-40): пузырь не должен размываться
      style={поднято ? { zIndex: 45 } : undefined}
      onPointerDown={вниз}
      onPointerMove={движение}
      onPointerUp={вверх}
      onPointerCancel={вверх}
      onContextMenu={(e) => {
        e.preventDefault();
        бросить();
        const box = корпус.current?.getBoundingClientRect();
        if (box) onMenu(m, box);
      }}
      onClickCapture={(e) => {
        // Тап после долгого нажатия или свайпа не должен доехать до кружка:
        // иначе жест «ответить» заодно включал бы звук
        if (!съестьКлик.current) return;
        съестьКлик.current = false;
        e.preventDefault();
        e.stopPropagation();
      }}
    >
      {/* Потолок ширины держит КОРПУС, а не пузырь внутри него. У пузыря
          max-w в процентах считался от самого корпуса: при вычислении
          внутренней ширины проценты игнорируются, корпус брал max-content,
          и 78% отмерялись уже от него — пузырь недобирал пятую часть строки,
          рвал короткие фразы на два ряда и отрывал от себя реакции. */}
      <div
        ref={корпус}
        className="relative max-w-[78%]"
        style={{
          transform: сдвиг ? `translateX(${сдвиг.toFixed(1)}px)` : undefined,
          transition: тянем ? "none" : "transform 0.24s cubic-bezier(0.2,0.8,0.2,1)",
        }}
      >
        <span
          aria-hidden="true"
          className="absolute top-1/2 -translate-y-1/2 w-7 h-7 rounded-full
                     flex items-center justify-center bg-surface-2 text-text-secondary"
          style={{
            right: "calc(100% + 8px)",
            opacity: Math.min(1, сдвиг / ПОРОГ),
            transform: `translateY(-50%) scale(${0.7 + 0.3 * Math.min(1, сдвиг / ПОРОГ)})`,
          }}
        >
          <CornerUpLeft size={15} />
        </span>
        {children}
        <span
          aria-hidden="true"
          className="absolute inset-0 rounded-[20px] pointer-events-none
                     transition-opacity duration-300"
          style={{
            opacity: подсвечено ? 1 : 0,
            boxShadow: "0 0 0 2px var(--color-accent)",
          }}
        />
      </div>

      <ReactionRow
        reactions={m.reactions}
        myId={myId}
        mine={mine}
        onToggle={(key) => onToggleReaction(m, key)}
      />
    </div>
  );
}
