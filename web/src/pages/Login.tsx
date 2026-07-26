import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { Heart, Sparkles, MessageCircle, Zap } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { authWithTelegram, authDev, type UserProfile } from "../lib/api";
import { getInitData, initTelegram, isInTelegram } from "../lib/telegram";
import { useStore } from "../lib/store";

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

  useEffect(() => {
    initTelegram();
    // Auto-login if inside Telegram Mini App
    if (isInTelegram() && getInitData()) {
      handleTelegramLogin();
    }
  }, []);

  const finishLogin = (token: string, user: UserProfile) => {
    setToken(token);
    setUser(user);
    // Redirect based on onboarding status
    if (!user.display_name || !user.photos?.length) {
      navigate("/onboarding");
    } else {
      navigate("/discover");
    }
  };

  const handleTelegramLogin = async () => {
    const initData = getInitData();
    if (!initData) {
      setError("Откройте приложение через Telegram-бота — или войдите как гость ниже");
      return;
    }

    setLoading(true);
    setError("");
    try {
      const { token, user } = await authWithTelegram(initData);
      finishLogin(token, user);
    } catch (e: any) {
      setError(e.response?.data?.detail || "Ошибка авторизации");
    } finally {
      setLoading(false);
    }
  };

  const handleGuestLogin = async () => {
    setLoading(true);
    setError("");
    try {
      const { token, user } = await authDev(getDeviceId());
      finishLogin(token, user);
    } catch (e: any) {
      setError(e.response?.data?.detail || "Гостевой вход недоступен");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-6 max-w-md mx-auto">
      <motion.div
        initial={{ scale: 0.5, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: "spring", damping: 12 }}
        className="text-center mb-12"
      >
        <div className="flex justify-center mb-6">
          <motion.div
            animate={{ rotate: [0, -10, 10, 0] }}
            transition={{ repeat: Infinity, duration: 3 }}
            className="w-24 h-24 rounded-full bg-gradient-to-br from-accent to-warn flex items-center justify-center"
          >
            <Heart size={48} className="text-white" fill="white" />
          </motion.div>
        </div>

        <h1 className="text-4xl font-bold mb-2 bg-gradient-to-r from-accent via-warn to-accent bg-clip-text text-transparent">
          Souldawn Dating
        </h1>
        <p className="text-text-muted">Знакомства нового поколения</p>
      </motion.div>

      {/* Features */}
      <div className="space-y-4 mb-12 w-full">
        {[
          { icon: Sparkles, title: "AI-совместимость", desc: "Умный подбор мэтчей на базе GLM-5.2" },
          { icon: MessageCircle, title: "Реал-тайм чат", desc: "Общайтесь мгновенно после мэтча" },
          { icon: Zap, title: "3 платформы", desc: "Telegram, Web и iOS — синхронизированы" },
        ].map((feat, i) => (
          <motion.div
            key={i}
            initial={{ x: -30, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            transition={{ delay: 0.2 + i * 0.1 }}
            className="flex items-center gap-4 p-4 bg-surface rounded-2xl"
          >
            <div className="w-12 h-12 rounded-full bg-accent/20 flex items-center justify-center shrink-0">
              <feat.icon className="text-accent" size={22} />
            </div>
            <div>
              <h3 className="font-semibold">{feat.title}</h3>
              <p className="text-sm text-text-muted">{feat.desc}</p>
            </div>
          </motion.div>
        ))}
      </div>

      {error && (
        <div className="mb-4 px-4 py-3 bg-danger/20 border border-danger/40 rounded-xl text-danger text-sm w-full">
          {error}
        </div>
      )}

      {/* Login button */}
      <button
        onClick={handleTelegramLogin}
        disabled={loading}
        className="w-full py-4 bg-gradient-to-r from-accent to-warn text-white font-bold rounded-full hover:opacity-90 transition disabled:opacity-50"
      >
        {loading ? "Входим..." : "Войти через Telegram"}
      </button>

      {!isInTelegram() && (
        <>
          <button
            onClick={handleGuestLogin}
            disabled={loading}
            className="w-full py-3 mt-3 bg-surface text-text font-semibold rounded-full hover:bg-surface/80 transition disabled:opacity-50"
          >
            Продолжить как гость
          </button>
          <p className="text-xs text-text-muted mt-4 text-center">
            Для входа через Telegram откройте приложение через бота.
          </p>
        </>
      )}
    </div>
  );
}
