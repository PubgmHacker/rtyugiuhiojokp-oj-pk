/**
 * Базовые UI-примитивы дизайн-системы Симп.
 * Все экраны собираются из них, чтобы вид и поведение были едиными.
 */
import { motion, type HTMLMotionProps } from "framer-motion";
import { WifiOff } from "lucide-react";
import { useId } from "react";
import type { ComponentType, ReactNode } from "react";
import { haptic, type HapticKind } from "../lib/haptics";

/* ── Кнопка ─────────────────────────────────────────────────── */

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "glass";
type ButtonSize = "sm" | "md" | "lg";

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  // Главный CTA: перелив факела. Мелкие accent-элементы (пилюли, иконки)
  // остаются на плоском --color-accent.
  primary: "btn-torch text-on-accent",
  secondary: "bg-surface-2 text-text border border-hairline",
  ghost: "bg-transparent text-text-secondary",
  danger: "bg-danger/15 text-danger border border-danger/30",
  glass: "glass text-text",
};

const SIZE_CLASS: Record<ButtonSize, string> = {
  // Радиусы — как у кнопок Plink: 12 / 14 / 18 у выступающей h52
  sm: "h-10 px-4 text-sm rounded-[12px]",
  md: "h-12 px-6 text-[15px] rounded-[14px]",
  lg: "h-[52px] px-8 text-[15px] rounded-[18px]",
};

interface ButtonProps extends Omit<HTMLMotionProps<"button">, "children"> {
  children: ReactNode;
  variant?: ButtonVariant;
  size?: ButtonSize;
  fullWidth?: boolean;
  loading?: boolean;
  hapticKind?: HapticKind;
}

export function Button({
  children,
  variant = "primary",
  size = "md",
  fullWidth,
  loading,
  disabled,
  hapticKind = "light",
  className = "",
  onClick,
  ...rest
}: ButtonProps) {
  const isDisabled = disabled || loading;
  // Disabled primary: отдельный muted-стиль. opacity на --gradient-torch
  // даёт «грязный» коричнево-красный и серый текст — как сломанная кнопка.
  const surface =
    isDisabled && variant === "primary"
      ? "bg-surface-3 text-text-faint border border-hairline"
      : VARIANT_CLASS[variant];

  return (
    <motion.button
      whileTap={isDisabled ? undefined : { scale: 0.97 }}
      transition={{ type: "spring", stiffness: 520, damping: 30 }}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      onClick={(e) => {
        if (isDisabled) return;
        haptic(hapticKind);
        onClick?.(e);
      }}
      className={`
        ${surface} ${SIZE_CLASS[size]}
        ${fullWidth ? "w-full" : ""}
        inline-flex items-center justify-center gap-2 font-semibold
        tracking-[-0.01em] transition-colors
        disabled:pointer-events-none
        ${isDisabled && variant === "primary" ? "" : "disabled:opacity-45"}
        focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent
        ${className}
      `}
      {...rest}
    >
      {loading ? (
        <>
          <Spinner size={size === "lg" ? 22 : 18} />
          <span>{children}</span>
        </>
      ) : (
        children
      )}
    </motion.button>
  );
}

/* ── Круглая кнопка действия (дека) ─────────────────────────── */

interface IconButtonProps extends Omit<HTMLMotionProps<"button">, "children"> {
  children: ReactNode;
  label: string;
  size?: number;
  tone?: "primary" | "neutral" | "danger" | "success" | "warn" | "info" | "premium";
}

// Тушь тона. У primary и premium её задаёт сам рецепт стекла (см. СТЕКЛО),
// поэтому здесь пусто; нейтральная тоже без своего цвета — стекло берёт
// --liquid-ink темы, а text-text-secondary спорил бы с ним.
const TONE_CLASS: Record<NonNullable<IconButtonProps["tone"]>, string> = {
  primary: "",
  neutral: "",
  premium: "",
  danger: "text-danger",
  success: "text-success",
  warn: "text-warn",
  info: "text-info",
};

/* Рецепт стекла под тон. Кнопки деки стоят на фоне страницы, а не поверх
   фото, поэтому базовый liquid берёт цвета темы; модификатор liquid-photo
   нужен только тому, кто действительно лежит на снимке — его передают
   через className.
   Главное действие — перелив факела; премиум (суперлайк, буст, подарок) —
   мягкое золото в кромке и туши, в стороне от акцента, чтобы не спорить
   с лайком. */
const СТЕКЛО: Record<NonNullable<IconButtonProps["tone"]>, string> = {
  primary: "liquid-primary",
  premium: "liquid liquid-gold",
  neutral: "liquid",
  danger: "liquid",
  success: "liquid",
  warn: "liquid",
  info: "liquid",
};

export function IconButton({
  children,
  label,
  size = 56,
  tone = "neutral",
  className = "",
  onClick,
  disabled,
  ...rest
}: IconButtonProps) {
  return (
    <motion.button
      aria-label={label}
      whileTap={disabled ? undefined : { scale: 0.88 }}
      transition={{ type: "spring", stiffness: 560, damping: 28 }}
      disabled={disabled}
      onClick={(e) => {
        if (disabled) return;
        haptic("medium");
        onClick?.(e);
      }}
      style={{ width: size, height: size }}
      className={`
        ${СТЕКЛО[tone]} ${TONE_CLASS[tone]}
        rounded-full flex items-center justify-center
        disabled:opacity-30 disabled:pointer-events-none
        focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent
        ${className}
      `}
      {...rest}
    >
      {children}
    </motion.button>
  );
}

/* ── Спиннер ────────────────────────────────────────────────── */

export function Spinner({ size = 20 }: { size?: number }) {
  return (
    <span
      role="status"
      aria-label="Загрузка"
      style={{ width: size, height: size, borderWidth: Math.max(2, size / 10) }}
      className="inline-block rounded-full border-current border-t-transparent animate-spin opacity-80"
    />
  );
}

/* ── Карточка / поверхность ─────────────────────────────────── */

export function Card({
  children,
  className = "",
  ...rest
}: React.HTMLAttributes<HTMLDivElement> & { children: ReactNode }) {
  return (
    <div
      className={`glass rounded-[20px] ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}

/* ── Чип (интересы, фильтры) ────────────────────────────────── */

export function Chip({
  children,
  active,
  onClick,
  className = "",
}: {
  children: ReactNode;
  active?: boolean;
  onClick?: () => void;
  className?: string;
}) {
  const interactive = !!onClick;
  return (
    <motion.button
      type="button"
      aria-pressed={interactive ? !!active : undefined}
      whileTap={interactive ? { scale: 0.94 } : undefined}
      onClick={
        interactive
          ? () => {
              haptic("select");
              onClick!();
            }
          : undefined
      }
      className={`
        min-h-[44px] min-w-[44px] px-3.5 py-2 rounded-full text-sm font-medium
        transition-colors focus-visible:outline-2 focus-visible:outline-offset-2
        focus-visible:outline-accent
        ${
          active
            ? "bg-accent text-on-accent"
            : "bg-surface-2 text-text-secondary border border-hairline"
        }
        ${interactive ? "" : "cursor-default"}
        ${className}
      `}
    >
      {children}
    </motion.button>
  );
}

/* ── Тумблер ────────────────────────────────────────────────── */

/**
 * Презентационный тумблер: состоянием и aria владеет строка-кнопка вокруг
 * (см. PrivacyToggle в Profile и «Только подтверждённые» в Discover), чтобы
 * зона нажатия была всей строкой, а не пятачком 46×27.
 */
export function Toggle({ on }: { on: boolean }) {
  return (
    <span
      className={`w-[46px] h-[27px] rounded-full relative shrink-0 transition-colors ${
        on ? "bg-success" : "bg-surface-3"
      }`}
    >
      <motion.span
        layout
        transition={{ type: "spring", stiffness: 520, damping: 32 }}
        className="absolute top-[3px] w-[21px] h-[21px] bg-white rounded-full"
        style={{ left: on ? 22 : 3 }}
      />
    </span>
  );
}

/* ── Бейдж верификации ──────────────────────────────────────── */

/* Силуэт печати построен генератором: 12 лепестков, квадратичная Безье
   на каждый лепесток с контролем C = 2P − (V0+V1)/2, поэтому кривая
   проходит ровно через вершину, а множество точек совпадает со своим
   зеркалом x → 24−x. Прежний путь был набран руками: точка (9.6, 20.2)
   вместо (9.6, 18.2) — левая половина висела на 2 px ниже, отсюда «кривая
   галочка». Глиф отцентрован по bbox в (12, 12). */
const ПЕЧАТЬ =
  "M14.21 3.74Q12 -0.84 9.79 3.74Q5.58 0.88 5.95 5.95Q0.88 5.58 3.74 9.79" +
  "Q-0.84 12 3.74 14.21Q0.88 18.42 5.95 18.05Q5.58 23.12 9.79 20.26" +
  "Q12 24.84 14.21 20.26Q18.42 23.12 18.05 18.05Q23.12 18.42 20.26 14.21" +
  "Q24.84 12 20.26 9.79Q23.12 5.58 18.05 5.95Q18.42 0.88 14.21 3.74Z";

export function VerifiedBadge({
  size = 18,
  title = "Профиль верифицирован",
}: {
  size?: number;
  title?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-label={title}
      role="img"
      className="shrink-0"
    >
      <path d={ПЕЧАТЬ} fill="var(--color-verified)" />
      <path
        d="M8.72 12.28L10.88 14.48L15.27 9.53"
        stroke="#fff"
        strokeWidth="2.15"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/* ── Бейдж команды ──────────────────────────────────────────────
   Тот же силуэт печати, но золотой и с искрой вместо галочки: рядом
   с синей верификацией читается как другой класс, а не как её вариант.
   Искра — тот же генератор, 4 острых луча, боковины впалые (контроль
   у центра), симметрия по обеим осям. */
const ИСКРА =
  "M12 5.9Q11.05 11.05 5.9 12Q11.05 12.95 12 18.1Q12.95 12.95 18.1 12" +
  "Q12.95 11.05 12 5.9Z";

export function OfficialBadge({
  size = 18,
  title = "Аккаунт команды Симпа",
}: {
  size?: number;
  title?: string;
}) {
  const uid = useId();
  const grad = `official-${uid}`;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-label={title}
      role="img"
      className="shrink-0"
    >
      <defs>
        <linearGradient id={grad} x1="4" y1="2" x2="20" y2="22" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="var(--color-official-hi)" />
          <stop offset="1" stopColor="var(--color-official)" />
        </linearGradient>
      </defs>
      <path d={ПЕЧАТЬ} fill={`url(#${grad})`} />
      <path d={ИСКРА} fill="#fff" />
    </svg>
  );
}

/* Один знак на человека, а не два. Золото сильнее синего: «мы» важнее,
   чем «лицо проверено», а два бейджа подряд на 14 px превращаются в кашу.
   Все экраны зовут именно этот компонент, поэтому правило живёт в одном
   месте и не расходится между чатом, декой и анкетой. */
export function IdentityBadge({
  profile,
  size = 18,
}: {
  profile: { is_verified?: boolean | null; is_official?: boolean | null };
  size?: number;
}) {
  if (profile.is_official) return <OfficialBadge size={size} />;
  if (profile.is_verified) return <VerifiedBadge size={size} />;
  return null;
}

/* ── Скелетон ───────────────────────────────────────────────── */

export function Skeleton({
  className = "",
  style,
}: {
  className?: string;
  style?: React.CSSProperties;
}) {
  return <div style={style} className={`skeleton rounded-[var(--radius-tile)] ${className}`} />;
}

/* ── Пустое состояние ───────────────────────────────────────── */

/** Иконка lucide: компонент, а не строка — эмодзи в интерфейсе не используются. */
export type ИконкаСостояния = ComponentType<{
  size?: number | string;
  className?: string;
  strokeWidth?: number | string;
}>;

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: ИконкаСостояния;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-8 py-16 text-center">
      <motion.div
        aria-hidden="true"
        initial={{ scale: 0.8, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: "spring", stiffness: 260, damping: 20 }}
        className="empty-glyph mb-5"
      >
        <Icon size={34} strokeWidth={1.6} />
      </motion.div>
      <h2 className="text-heading font-bold mb-2">{title}</h2>
      {description && (
        <p className="text-text-muted text-[15px] leading-relaxed max-w-[38ch] mb-7">
          {description}
        </p>
      )}
      {action}
    </div>
  );
}

/* ── Сбой загрузки ──────────────────────────────────────────── */

/** Ветка «данные не приехали». Показывать вместо неё пустоту нельзя:
 *  «пока пусто» при упавшей сети — ложь, из-за которой человек уходит,
 *  думая, что лайков/лент/записей действительно нет. */
export function LoadError({
  onRetry,
  title = "Не удалось загрузить",
  description = "Проверьте соединение и попробуйте снова.",
}: {
  onRetry: () => void;
  title?: string;
  description?: string;
}) {
  return (
    <EmptyState
      icon={WifiOff}
      title={title}
      description={description}
      action={
        <Button variant="secondary" size="md" onClick={onRetry}>
          Повторить
        </Button>
      }
    />
  );
}

/* ── Заголовок экрана ───────────────────────────────────────── */

export function ScreenHeader({
  title,
  subtitle,
  left,
  right,
  gradient,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  left?: ReactNode;
  right?: ReactNode;
  gradient?: boolean;
}) {
  return (
    <header className="chrome sticky top-0 z-30 safe-top border-b border-hairline/60">
      <span aria-hidden className="header-fade" />
      <div className="flex items-center gap-3 px-4 pb-3 min-h-[52px]">
        {left}
        <div className="flex-1 min-w-0">
          <h1
            className={`text-[22px] font-extrabold tracking-[-0.028em] truncate ${
              gradient ? "text-gradient" : ""
            }`}
          >
            {title}
          </h1>
          {subtitle && (
            <p className="text-caption text-text-muted truncate mt-0.5">{subtitle}</p>
          )}
        </div>
        {right}
      </div>
    </header>
  );
}
