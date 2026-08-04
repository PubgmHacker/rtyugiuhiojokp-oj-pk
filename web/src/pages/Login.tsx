import { useState, useEffect, useCallback, useRef } from "react";
import { motion } from "framer-motion";
import { Heart } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { authWithTelegram, authDev, type UserProfile } from "../lib/api";
import { getInitData, initTelegram, isInTelegram } from "../lib/telegram";
import { useStore } from "../lib/store";
import { haptic } from "../lib/haptics";
import { openExternal } from "../lib/native";
import { Button, Spinner } from "../components/ui";

const SITE_URL = import.meta.env.VITE_SITE_URL || "https://souldawn.app";
const BOT_USERNAME = import.meta.env.VITE_BOT_USERNAME || "souldawn_bot";

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
  const inTelegram = isInTelegram();

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
      {/* Атмосферный фон */}
      <div
        aria-hidden
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(70% 50% at 50% 8%, rgb(255 61 113 / 0.28), transparent 70%)," +
            "radial-gradient(60% 45% at 85% 30%, rgb(168 85 247 / 0.2), transparent 70%)," +
            "radial-gradient(70% 40% at 10% 75%, rgb(255 196 107 / 0.14), transparent 70%)",
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
          Знакомства, которые начинаются с рассвета
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
      className="w-24 h-24 rounded-[28px] bg-dawn glow-rose
                 flex items-center justify-center shrink-0"
    >
      <Heart size={46} fill="#fff" className="text-white" />
    </motion.div>
  );
}
