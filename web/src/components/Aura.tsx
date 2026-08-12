/**
 * Кольцо ауры вокруг аватара.
 *
 * Одно место на всё приложение: кольцо истории, аватар в списке пар,
 * шапка анкеты. Разные реализации разъехались бы по толщине и зазору —
 * а именно постоянство толщины делает кольцо признаком, а не украшением.
 */
import { auraOf } from "../lib/aura";

interface AuraRingProps {
  /** Семя ауры — user_id. */
  seed: string;
  /** Фотография. Пусто — покажем первую букву имени. */
  src?: string | null;
  name?: string;
  size?: number;
  /** Кольцо гаснет: история просмотрена, человек не в сети. */
  dim?: boolean;
  /** Кольца нет совсем — обычный аватар. */
  bare?: boolean;
  ring?: number;
  className?: string;
}

export function AuraRing({
  seed,
  src,
  name,
  size = 56,
  dim = false,
  bare = false,
  ring = 2.5,
  className = "",
}: AuraRingProps) {
  const aura = auraOf(seed);
  const pad = bare ? 0 : ring;
  // Зазор между кольцом и фотографией: без него кольцо читается как
  // обводка снимка, а не как отдельный признак человека.
  const gap = bare ? 0 : 2;
  const inner = size - (pad + gap) * 2;

  return (
    <div
      className={`relative shrink-0 ${className}`}
      style={{
        width: size,
        height: size,
        padding: pad,
        borderRadius: "50%",
        background: bare ? "transparent" : aura.ring,
        opacity: dim ? 0.32 : 1,
        transition: "opacity 180ms ease",
      }}
    >
      <div
        className="grid h-full w-full place-items-center overflow-hidden rounded-full"
        style={{ background: "var(--color-bg)", padding: gap }}
      >
        {src ? (
          <img
            src={src}
            alt={name || ""}
            loading="lazy"
            className="h-full w-full rounded-full object-cover"
            style={{ width: inner, height: inner }}
          />
        ) : (
          <div
            className="grid place-items-center rounded-full font-semibold text-white"
            style={{
              width: inner,
              height: inner,
              fontSize: Math.max(12, Math.round(inner * 0.4)),
              background: `linear-gradient(145deg, ${aura.from}, ${aura.to})`,
            }}
          >
            {(name || "?").trim().charAt(0).toUpperCase()}
          </div>
        )}
      </div>
    </div>
  );
}
