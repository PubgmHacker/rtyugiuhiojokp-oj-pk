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
  /**
   * Чем красим кольцо.
   *
   * aura — цвет человека: годится там, где аватар стоит один и цвет
   * работает подписью. brand — одно фирменное кольцо на всех: в полосе,
   * где кружки идут подряд, восемь разных оттенков складываются в радугу,
   * а имя всё равно напечатано под кружком, так что оттенок никого не
   * опознаёт. В brand погашенное кольцо — ровная волосяная линия, а не
   * яркая дуга в треть прозрачности: непросмотренное и просмотренное
   * должны отличаться рисунком, а не силой цвета.
   */
  tone?: "aura" | "brand";
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
  tone = "aura",
  ring = 2.5,
  className = "",
}: AuraRingProps) {
  const aura = auraOf(seed);
  const pad = bare ? 0 : ring;
  // Зазор между кольцом и фотографией: без него кольцо читается как
  // обводка снимка, а не как отдельный признак человека.
  const gap = bare ? 0 : 2;
  const inner = size - (pad + gap) * 2;
  const фирменное =
    "linear-gradient(150deg, var(--color-accent-soft), var(--color-accent) 52%, var(--color-accent-deep))";
  const кольцо = bare
    ? "transparent"
    : tone === "brand"
      ? dim
        ? "var(--color-hairline)"
        : фирменное
      : aura.ring;

  return (
    <div
      className={`relative shrink-0 ${className}`}
      style={{
        width: size,
        height: size,
        padding: pad,
        borderRadius: "50%",
        background: кольцо,
        // Гасим прозрачностью только цветное кольцо: фирменное уже меняет
        // сам цвет, и второе гашение сверху превращало бы его в грязь.
        opacity: dim && tone === "aura" ? 0.32 : 1,
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
