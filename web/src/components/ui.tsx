/**
 * Базовые UI-примитивы дизайн-системы Souldawn.
 * Все экраны собираются из них, чтобы вид и поведение были едиными.
 */
import { motion, type HTMLMotionProps } from "framer-motion";
import type { ReactNode } from "react";
import { haptic, type HapticKind } from "../lib/haptics";

/* ── Кнопка ─────────────────────────────────────────────────── */

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "glass";
type ButtonSize = "sm" | "md" | "lg";

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: "bg-dawn text-on-accent shadow-[var(--shadow-control)]",
  secondary: "bg-surface-2 text-text border border-hairline",
  ghost: "bg-transparent text-text-secondary",
  danger: "bg-danger/15 text-danger border border-danger/30",
  glass: "glass text-text",
};

const SIZE_CLASS: Record<ButtonSize, string> = {
  sm: "h-10 px-4 text-sm rounded-[var(--radius-control)]",
  md: "h-12 px-6 text-[15px] rounded-[var(--radius-control)]",
  lg: "h-[52px] px-8 text-[15px] rounded-[var(--radius-control)]",
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

  return (
    <motion.button
      whileTap={isDisabled ? undefined : { scale: 0.96 }}
      transition={{ type: "spring", stiffness: 520, damping: 30 }}
      disabled={isDisabled}
      onClick={(e) => {
        if (isDisabled) return;
        haptic(hapticKind);
        onClick?.(e);
      }}
      className={`
        ${VARIANT_CLASS[variant]} ${SIZE_CLASS[size]}
        ${fullWidth ? "w-full" : ""}
        inline-flex items-center justify-center gap-2 font-semibold
        tracking-[-0.01em] transition-opacity
        disabled:opacity-45 disabled:pointer-events-none
        focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent
        ${className}
      `}
      {...rest}
    >
      {loading ? <Spinner size={size === "lg" ? 22 : 18} /> : children}
    </motion.button>
  );
}

/* ── Круглая кнопка действия (дека) ─────────────────────────── */

interface IconButtonProps extends Omit<HTMLMotionProps<"button">, "children"> {
  children: ReactNode;
  label: string;
  size?: number;
  tone?: "primary" | "neutral" | "danger" | "success" | "warn" | "info";
}

const TONE_CLASS: Record<NonNullable<IconButtonProps["tone"]>, string> = {
  // Главное действие экрана: залитый акцентом круг, а не цветной глиф на
  // стекле. Столбец из пяти разноцветных иконок читается как страница
  // UI-кита — цвет должен быть один и означать «нажми сюда»
  primary: "bg-dawn text-white border-transparent",
  neutral: "text-text-secondary",
  danger: "text-danger",
  success: "text-success",
  warn: "text-warn",
  info: "text-info",
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
        ${tone === "primary" ? "" : "glass-strong"} ${TONE_CLASS[tone]}
        rounded-full flex items-center justify-center float-shadow
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
      className={`bg-surface border border-hairline rounded-[var(--radius-tile)] ${className}`}
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
        px-3.5 py-2 rounded-full text-sm font-medium transition-colors
        ${
          active
            ? "bg-dawn text-on-accent"
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

/* ── Бейдж верификации ──────────────────────────────────────── */

export function VerifiedBadge({ size = 18 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-label="Профиль верифицирован"
      role="img"
      className="shrink-0"
    >
      <path
        d="M12 2l2.4 1.8 3-.3 1 2.8 2.4 1.8-1 2.9 1 2.9-2.4 1.8-1 2.8-3-.3L12 22l-2.4-1.8-3 .3-1-2.8L3.2 15.9l1-2.9-1-2.9 2.4-1.8 1-2.8 3 .3L12 2z"
        fill="var(--color-verified)"
      />
      <path
        d="M8.5 12.2l2.3 2.3 4.7-4.7"
        stroke="#fff"
        strokeWidth="2.1"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
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

export function EmptyState({
  emoji,
  title,
  description,
  action,
}: {
  emoji: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-8 py-16 text-center">
      <motion.div
        initial={{ scale: 0.8, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: "spring", stiffness: 260, damping: 20 }}
        className="text-[56px] mb-5 leading-none"
      >
        {emoji}
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
