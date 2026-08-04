import { useState, useEffect, useCallback, useRef } from "react";
import { motion } from "framer-motion";
import { Heart } from "lucide-react";
import { useNavigate } from "react-router-dom";
import {
  authWithTelegram,
  authDev,
  authWithLinkCode,
  type UserProfile,
} from "../lib/api";
import { getInitData, initTelegram, isInTelegram } from "../lib/telegram";
import { useStore } from "../lib/store";
import { haptic } from "../lib/haptics";
import { openExternal, isNative } from "../lib/native";
import { Button, Spinner } from "../components/ui";

const SITE_URL = import.meta.env.VITE_SITE_URL || "https://souldawn.app";
const BOT_USERNAME = import.meta.env.VITE_BOT_USERNAME || "souldawn_bot";
const CODE_LENGTH = 6;

function getDeviceId(): string {
  let id = localStorage.getItem("sd_device_id");
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem("sd_device_id", id);
  }
  return id;
}

export default function Login() {
  const navigate = useNavigate();
  const { setUser, setToken } = useStore();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [code, setCode] = useState("");
  const inTelegram = isInTelegram();
  // Считываем один раз при монтировании: платформа за время жизни экрана
  // не меняется, а вызов в теле рендера означал бы, что способ входа
  // может переключиться прямо во время набора кода — стоит рантайму
  // Capacitor инициализироваться чуть позже первого рендера
  const [native] = useState(isNative);

  // Внутри Telegram initData уже есть — входим сами, без лишнего нажатия
  const autoTried = useRef(false);

  const finishLogin = useCallback(
    (token: string, user: UserProfile) => {
      setToken(token);
      setUser(user);
      haptic("success");
      const needsOnboarding = !user.display_name || !user.photos?.length;
      navigate(needsOnboarding ? "/onboarding" : "/discover", { replace: true });
    },
    [navigate, setToken, setUser]
  );

  const loginWithTelegram = useCallback(async () => {
    const initData = getInitData();
    if (!initData) {
      setError("Откройте приложение через Telegram-бота");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const { token, user } = await authWithTelegram(initData);
      finishLogin(token, user);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? "Не удалось войти. Попробуйте ещё раз.");
      haptic("error");
    } finally {
      setLoading(false);
    }
  }, [finishLogin]);

  const loginWithCode = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const { token, user } = await authWithLinkCode(code);
      finishLogin(token, user);
    } catch (e: any) {
      setError(
        e?.response?.data?.detail ??
          "Код неверный или устарел. Запросите новый командой /link у бота."
      );
      setCode("");
      haptic("error");
    } finally {
      setLoading(false);
    }
  }, [code, finishLogin]);

  const loginAsGuest = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const { token, user } = await authDev(getDeviceId());
      finishLogin(token, user);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? "Гостевой вход недоступен");
      haptic("error");
    } finally {
      setLoading(false);
    }
  }, [finishLogin]);

  useEffect(() => {
    initTelegram();
    if (inTelegram && getInitData() && !autoTried.current) {
      autoTried.current = true;
      loginWithTelegram();
    }
  }, [inTelegram, loginWithTelegram]);

  /* ── Автовход внутри Telegram ────────────────────────────── */
  if (inTelegram && loading) {
    return (
      <div className="h-screen-safe flex flex-col items-center justify-center gap-5">
        <Logo />
        <Spinner size={24} />
        <p className="text-[14px] text-text-muted">Входим…</p>
      </div>
    );
  }

  return (
    <div className="relative h-screen-safe overflow-hidden flex flex-col">
      {/* Сдержанная подсветка за логотипом: один холодный оттенок
          вместо трёх цветных пятен */}
      <div
        aria-hidden
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(80% 45% at 50% 12%, rgb(91 102 255 / 0.14), transparent 72%)",
        }}
      />

      <div className="relative flex-1 flex flex-col items-center justify-center px-6 safe-top">
        <Logo animated />

        <motion.h1
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1, type: "spring", stiffness: 320, damping: 28 }}
          className="text-display text-gradient text-center mt-7 mb-3"
        >
          Souldawn
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.18, type: "spring", stiffness: 320, damping: 28 }}
          className="text-[16px] text-text-secondary text-center max-w-[30ch] leading-relaxed"
        >
          Знакомства без спешки — по интересам, а не только по фото
        </motion.p>
      </div>

      {/* Действия */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.26, type: "spring", stiffness: 320, damping: 30 }}
        className="relative px-6 pb-7 safe-bottom flex flex-col gap-2.5"
      >
        {error && (
          <div
            role="alert"
            className="mb-1 px-4 py-3 rounded-[var(--radius-tile)]
                       bg-danger/12 border border-danger/30 text-danger text-[13.5px]"
          >
            {error}
          </div>
        )}

        {/* Нативное приложение: Telegram initData здесь недоступен, поэтому
            вход идёт по одноразовому коду, который выдаёт бот командой /link */}
        {native && !inTelegram ? (
          <>
            <label
              htmlFor="link-code"
              className="text-[13px] text-text-secondary text-center"
            >
              Введите код из бота — команда <code className="text-text">/link</code>
            </label>
            <input
              id="link-code"
              value={code}
              onChange={(e) => {
                setCode(e.target.value.replace(/\D/g, "").slice(0, CODE_LENGTH));
                setError("");
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && code.length === CODE_LENGTH && !loading) {
                  loginWithCode();
                }
              }}
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="000000"
              aria-label="Код входа из бота"
              className="w-full h-[56px] rounded-[var(--radius-control)]
                         bg-surface-2 border border-border text-center
                         text-[26px] tracking-[0.4em] font-semibold
                         text-text placeholder:text-text-faint
                         focus:outline-none focus:border-primary"
            />
            <Button
              size="lg"
              fullWidth
              onClick={loginWithCode}
              disabled={loading || code.length !== CODE_LENGTH}
            >
              {loading ? <Spinner size={20} /> : "Войти"}
            </Button>
            <Button
              variant="secondary"
              size="md"
              fullWidth
              onClick={() => openExternal(`https://t.me/${BOT_USERNAME}?start=link`)}
              disabled={loading}
            >
              Получить код в Telegram
            </Button>
          </>
        ) : (
          <>
            <Button
              size="lg"
              fullWidth
              onClick={
                inTelegram
                  ? loginWithTelegram
                  : () => openExternal(`https://t.me/${BOT_USERNAME}`)
              }
              disabled={loading}
            >
              {loading ? <Spinner size={20} /> : inTelegram ? "Войти" : "Открыть в Telegram"}
            </Button>

            {/* Гостевой вход живёт только при DEBUG на бэкенде: в проде
                запрос вернёт ошибку, поэтому показываем его как
                второстепенный путь и только вне Telegram */}
            {!inTelegram && (
              <Button
                variant="secondary"
                size="md"
                fullWidth
                onClick={loginAsGuest}
                disabled={loading}
              >
                Продолжить как гость
              </Button>
            )}
          </>
        )}

        <p className="mt-3 text-[11.5px] text-text-faint text-center leading-relaxed">
          Сервис только для лиц старше 18 лет. Продолжая, вы принимаете{" "}
          <a
            href={`${SITE_URL}/terms.html`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-text-muted underline underline-offset-2"
          >
            Условия
          </a>{" "}
          и{" "}
          <a
            href={`${SITE_URL}/privacy.html`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-text-muted underline underline-offset-2"
          >
            Политику конфиденциальности
          </a>
          .
        </p>
      </motion.div>
    </div>
  );
}

function Logo({ animated }: { animated?: boolean }) {
  return (
    <motion.div
      initial={animated ? { scale: 0.7, opacity: 0 } : false}
      animate={animated ? { scale: 1, opacity: 1 } : undefined}
      transition={{ type: "spring", stiffness: 300, damping: 20 }}
      className="w-[72px] h-[72px] rounded-[var(--radius-card)] bg-dawn
                 flex items-center justify-center shrink-0 float-shadow"
    >
      <Heart size={34} fill="#fff" className="text-white" />
    </motion.div>
  );
}
