import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Heart,
  Sparkles,
  Shield,
  MessageCircle,
  Zap,
  Globe,
  ChevronRight,
  X,
  Star,
  Download,
  Send,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useStore } from "../lib/store";

const BOT_TG_URL = `https://t.me/${import.meta.env.VITE_BOT_USERNAME || "souldawn_dating_bot"}`;
const APP_STORE_URL = "https://apps.apple.com/app/souldawn-dating/id000000000";

// ── Mock profiles for swipe demo ───────────────────────────────
const MOCK_PROFILES = [
  { name: "Анна", age: 24, city: "Москва", bio: "Люблю кофе, закаты и спонтанные поездки ☕️",
    photo: "https://placehold.co/600x800/ff6b9d/ffffff?text=%D0%90%D0%BD%D0%BD%D0%B0%2C+24",
    interests: ["☕ Кофе", "✈️ Путешествия", "📸 Фото"] },
  { name: "Мария", age: 27, city: "СПб", bio: "Йога, книги и долгие разговоры до утра 🧘‍♀️",
    photo: "https://placehold.co/600x800/c97b3d/ffffff?text=%D0%9C%D0%B0%D1%80%D0%B8%D1%8F%2C+27",
    interests: ["🧘 Йога", "📚 Чтение", "🍷 Вино"] },
  { name: "Елена", age: 23, city: "Казань", bio: "Художница в поиске вдохновения и тебя 🎨",
    photo: "https://placehold.co/600x800/6bff9d/0a0a1a?text=%D0%95%D0%BB%D0%B5%D0%BD%D0%B0%2C+23",
    interests: ["🎨 Искусство", "🎬 Кино", "☕ Кофе"] },
  { name: "Ольга", age: 26, city: "Екатеринбург", bio: "Бегаю марафоны и от тебя не убегу 🏃‍♀️",
    photo: "https://placehold.co/600x800/ffd93d/0a0a1a?text=%D0%9E%D0%BB%D1%8C%D0%B3%D0%B0%2C+26",
    interests: ["🏃 Спорт", "🏔 Походы", "🎵 Музыка"] },
];

// ════════════════════════════════════════════════════════════════
//  INTERACTIVE SWIPE DEMO
// ════════════════════════════════════════════════════════════════
function SwipeDemo() {
  const [index, setIndex] = useState(0);
  const [direction, setDirection] = useState<"like" | "nope" | null>(null);
  const [match, setMatch] = useState(false);

  // Auto-advance every 3.5s
  useEffect(() => {
    const timer = setTimeout(() => {
      handleSwipe("like");
    }, 3500);
    return () => clearTimeout(timer);
  }, [index]);

  const handleSwipe = (dir: "like" | "nope") => {
    setDirection(dir);
    setTimeout(() => {
      // Random match on like
      if (dir === "like" && Math.random() > 0.5) {
        setMatch(true);
        setTimeout(() => setMatch(false), 1500);
      }
      setIndex((prev) => (prev + 1) % MOCK_PROFILES.length);
      setDirection(null);
    }, 400);
  };

  const profile = MOCK_PROFILES[index];

  return (
    <div className="relative w-full h-full">
      {/* Match overlay */}
      <AnimatePresence>
        {match && (
          <motion.div
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0, opacity: 0 }}
            className="absolute inset-0 z-50 flex items-center justify-center bg-black/80 rounded-3xl"
          >
            <div className="text-center">
              <motion.div
                animate={{ scale: [1, 1.2, 1] }}
                transition={{ repeat: Infinity, duration: 0.8 }}
              >
                <Heart size={60} className="text-accent" fill="currentColor" />
              </motion.div>
              <p className="text-2xl font-bold mt-2 bg-gradient-to-r from-accent to-warn bg-clip-text text-transparent">
                Это мэтч!
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Card */}
      <AnimatePresence mode="popLayout">
        <motion.div
          key={index}
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{
            scale: 1,
            opacity: 1,
            x: direction === "like" ? 500 : direction === "nope" ? -500 : 0,
            rotate: direction === "like" ? 25 : direction === "nope" ? -25 : 0,
          }}
          exit={{ scale: 0.9, opacity: 0 }}
          transition={{ type: "spring", damping: 20 }}
          drag="x"
          dragSnapToOrigin
          onDragEnd={(_, info) => {
            if (info.offset.x > 80) handleSwipe("like");
            else if (info.offset.x < -80) handleSwipe("nope");
          }}
          className="absolute inset-0 rounded-3xl overflow-hidden cursor-grab active:cursor-grabbing shadow-2xl"
        >
          <img src={profile.photo} alt={profile.name} className="w-full h-full object-cover" />
          <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent" />

          {/* Like / Nope stamps */}
          <motion.div
            animate={{ opacity: direction === "like" ? 1 : 0 }}
            className="absolute top-6 left-4 border-4 border-success rounded-2xl px-4 py-2 rotate-[-20deg]"
          >
            <span className="text-success text-2xl font-black">LIKE</span>
          </motion.div>
          <motion.div
            animate={{ opacity: direction === "nope" ? 1 : 0 }}
            className="absolute top-6 right-4 border-4 border-danger rounded-2xl px-4 py-2 rotate-[20deg]"
          >
            <span className="text-danger text-2xl font-black">NOPE</span>
          </motion.div>

          {/* Info */}
          <div className="absolute bottom-0 left-0 right-0 p-5 text-white">
            <div className="flex items-end gap-2 mb-2">
              <h3 className="text-2xl font-bold">{profile.name}</h3>
              <span className="text-xl">{profile.age}</span>
            </div>
            <p className="text-sm opacity-90 mb-2">{profile.bio}</p>
            <div className="flex flex-wrap gap-1.5">
              {profile.interests.map((tag, i) => (
                <span key={i} className="text-xs px-2 py-1 rounded-full bg-white/20 backdrop-blur-sm">
                  {tag}
                </span>
              ))}
            </div>
          </div>
        </motion.div>
      </AnimatePresence>

      {/* Action buttons (static, decorative) */}
      <div className="absolute -bottom-16 left-0 right-0 flex items-center justify-center gap-3">
        <button
          onClick={() => handleSwipe("nope")}
          className="w-11 h-11 bg-surface rounded-full flex items-center justify-center shadow-lg"
        >
          <X size={20} className="text-danger" strokeWidth={3} />
        </button>
        <button
          onClick={() => handleSwipe("like")}
          className="w-11 h-11 bg-surface rounded-full flex items-center justify-center shadow-lg"
        >
          <Heart size={20} className="text-success" fill="currentColor" />
        </button>
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════
//  MAIN LANDING PAGE
// ════════════════════════════════════════════════════════════════
export default function Landing() {
  const navigate = useNavigate();
  const { token } = useStore();

  const features = [
    { icon: Sparkles, title: "AI Matchmaker", desc: "GLM-5.2 анализирует ваши анкеты и интересы, подбирая пары с совместимостью до 100%.", color: "text-accent" },
    { icon: Shield, title: "AI-модерация 24/7", desc: "Каждое фото и текст проверяются нейросетью. Мошенники и спам блокируются автоматически.", color: "text-success" },
    { icon: Zap, title: "Молниеносные мэтчи", desc: "Реал-тайм уведомления через WebSocket. Узнаёте о мэтче мгновенно — в Telegram, Web или iOS.", color: "text-warn" },
    { icon: Globe, title: "3 платформы", desc: "Telegram-бот, веб-сайт и нативное iOS-приложение. Всё синхронизировано в реальном времени.", color: "text-accent" },
    { icon: Heart, title: "Верификация профилей", desc: "Голубая галочка для проверенных пользователей. Никаких фейков и ботов.", color: "text-success" },
    { icon: MessageCircle, title: "Умный чат", desc: "AI-подсказки для начала диалога. Никогда не молчите, не зная что написать.", color: "text-warn" },
  ];

  const steps = [
    { num: "01", title: "Создай анкету", desc: "Загрузи фото, расскажи о себе. AI поможет составить идеальное описание." },
    { num: "02", title: "Свайпай", desc: "Смотри анкеты, поставь 👍 тем, кто понравился. Свайп вправо — лайк." },
    { num: "03", title: "Получай мэтчи", desc: "Взаимный лайк — это мэтч! AI объяснит, почему вы подходите друг другу." },
    { num: "04", title: "Общайся", desc: "Начни чат прямо сейчас. Реал-тайм сообщения в любой из 3 платформ." },
  ];

  return (
    <div className="min-h-screen bg-gradient-to-b from-[#0a0a1a] via-[#12122a] to-[#0a0a1a]">
      {/* Nav */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-bg/80 backdrop-blur-lg border-b border-white/5 safe-top">
        <div className="max-w-6xl mx-auto flex items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-accent to-warn flex items-center justify-center">
              <Heart size={18} fill="white" className="text-white" />
            </div>
            <span className="font-bold text-lg bg-gradient-to-r from-accent to-warn bg-clip-text text-transparent">
              Souldawn
            </span>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate(token ? "/discover" : "/login")}
              className="text-sm text-text-muted hover:text-text transition"
            >
              Войти
            </button>
            <a
              href={BOT_TG_URL}
              target="_blank"
              rel="noopener"
              className="px-4 py-2 bg-gradient-to-r from-accent to-warn text-white text-sm font-semibold rounded-full hover:opacity-90 transition"
            >
              Начать
            </a>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="relative pt-32 pb-20 px-4 overflow-hidden">
        <div className="absolute top-20 left-1/4 w-72 h-72 bg-accent/20 rounded-full blur-[100px] pointer-events-none" />
        <div className="absolute top-40 right-1/4 w-72 h-72 bg-warn/20 rounded-full blur-[100px] pointer-events-none" />

        <div className="max-w-6xl mx-auto grid lg:grid-cols-2 gap-12 items-center relative">
          <div className="text-center lg:text-left">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="inline-flex items-center gap-2 px-3 py-1 bg-accent/10 border border-accent/30 rounded-full mb-6"
            >
              <Sparkles size={14} className="text-accent" />
              <span className="text-xs text-accent">Powered by GLM-5.2 AI</span>
            </motion.div>

            <motion.h1
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
              className="text-5xl sm:text-6xl font-bold leading-tight mb-6"
            >
              Знакомства
              <br />
              <span className="bg-gradient-to-r from-accent via-warn to-accent bg-clip-text text-transparent">
                нового поколения
              </span>
            </motion.h1>

            <motion.p
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
              className="text-lg text-text-muted mb-8 max-w-md mx-auto lg:mx-0"
            >
              AI подбирает идеальные пары, модерация защищает от мошенников,
              а ты просто свайпаешь и находишь любовь.
            </motion.p>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 }}
              className="flex flex-col sm:flex-row gap-4 justify-center lg:justify-start"
            >
              <a
                href={BOT_TG_URL}
                target="_blank"
                rel="noopener"
                className="flex items-center justify-center gap-2 px-8 py-4 bg-gradient-to-r from-accent to-warn text-white font-bold rounded-2xl hover:scale-105 transition shadow-xl shadow-accent/30"
              >
                <Send size={20} />
                Открыть в Telegram
              </a>
              <a
                href={APP_STORE_URL}
                target="_blank"
                rel="noopener"
                className="flex items-center justify-center gap-2 px-8 py-4 bg-white text-black font-bold rounded-2xl hover:scale-105 transition"
              >
                <Download size={20} />
                App Store
              </a>
            </motion.div>

            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.4 }}
              className="flex items-center gap-6 mt-8 justify-center lg:justify-start text-sm text-text-muted"
            >
              <span className="flex items-center gap-1">
                <Shield size={16} className="text-success" /> Безопасно
              </span>
              <span className="flex items-center gap-1">
                <Zap size={16} className="text-warn" /> Бесплатно
              </span>
              <span className="flex items-center gap-1">
                <Star size={16} className="text-accent" fill="currentColor" /> 4.8★
              </span>
            </motion.div>
          </div>

          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.3 }}
            className="relative mx-auto w-[300px] h-[460px]"
          >
            <SwipeDemo />
          </motion.div>
        </div>
      </section>

      {/* Stats bar */}
      <section className="border-y border-white/5 py-10">
        <div className="max-w-5xl mx-auto px-4 grid grid-cols-2 md:grid-cols-4 gap-6 text-center">
          {[
            { value: "AI", label: "Умный подбор мэтчей" },
            { value: "<1с", label: "Реал-тайм уведомления" },
            { value: "3", label: "Платформы: TG · Web · iOS" },
            { value: "18+", label: "Безопасные знакомства" },
          ].map((s, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.1 }}
            >
              <p className="text-3xl font-bold bg-gradient-to-r from-accent to-warn bg-clip-text text-transparent">
                {s.value}
              </p>
              <p className="text-sm text-text-muted mt-1">{s.label}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section className="py-20 px-4">
        <div className="max-w-5xl mx-auto">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="text-center mb-14"
          >
            <h2 className="text-4xl font-bold mb-4">
              Почему{" "}
              <span className="bg-gradient-to-r from-accent to-warn bg-clip-text text-transparent">
                Souldawn
              </span>
              ?
            </h2>
            <p className="text-text-muted max-w-xl mx-auto">
              Мы взяли лучшее от Tinder и Telegram-ботов, добавили AI — и получилось
              то, чего не хватает рынку знакомств.
            </p>
          </motion.div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            {features.map((feat, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 30 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.08 }}
                className="bg-surface rounded-2xl p-6 hover:bg-surface/80 transition border border-white/5"
              >
                <div className={`w-12 h-12 rounded-xl bg-white/5 flex items-center justify-center mb-4`}>
                  <feat.icon size={24} className={feat.color} />
                </div>
                <h3 className="text-lg font-semibold mb-2">{feat.title}</h3>
                <p className="text-sm text-text-muted leading-relaxed">{feat.desc}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="py-20 px-4 bg-bg/50">
        <div className="max-w-4xl mx-auto">
          <motion.h2
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="text-4xl font-bold text-center mb-14"
          >
            Как это работает
          </motion.h2>

          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {steps.map((step, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 30 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.1 }}
                className="relative"
              >
                <div className="text-5xl font-bold text-accent/20 mb-3">{step.num}</div>
                <h3 className="text-lg font-semibold mb-2">{step.title}</h3>
                <p className="text-sm text-text-muted">{step.desc}</p>
                {i < steps.length - 1 && (
                  <ChevronRight className="hidden lg:block absolute top-6 -right-3 text-text-muted/30" size={20} />
                )}
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-20 px-4">
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          whileInView={{ opacity: 1, scale: 1 }}
          viewport={{ once: true }}
          className="max-w-3xl mx-auto text-center bg-gradient-to-br from-accent/10 to-warn/10 border border-accent/30 rounded-3xl p-10 sm:p-16"
        >
          <Heart size={48} className="text-accent mx-auto mb-4 heart-beat" fill="currentColor" />
          <h2 className="text-3xl sm:text-4xl font-bold mb-4">
            Готов(а) найти свою пару?
          </h2>
          <p className="text-text-muted mb-8 max-w-md mx-auto">
            Присоединяйся бесплатно. Регистрация занимает меньше минуты.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <a
              href={BOT_TG_URL}
              target="_blank"
              rel="noopener"
              className="flex items-center justify-center gap-2 px-8 py-4 bg-gradient-to-r from-accent to-warn text-white font-bold rounded-2xl hover:scale-105 transition shadow-xl shadow-accent/30"
            >
              <Send size={20} />
              Открыть в Telegram
            </a>
            <a
              href={APP_STORE_URL}
              target="_blank"
              rel="noopener"
              className="flex items-center justify-center gap-2 px-8 py-4 bg-white text-black font-bold rounded-2xl hover:scale-105 transition"
            >
              <Download size={20} />
              Скачать для iOS
            </a>
          </div>
        </motion.div>
      </section>

      {/* Footer */}
      <footer className="border-t border-white/5 py-10 px-4">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-accent to-warn flex items-center justify-center">
              <Heart size={14} fill="white" className="text-white" />
            </div>
            <span className="font-bold text-sm">Souldawn Dating</span>
          </div>
          <div className="flex gap-6 text-xs text-text-muted">
            <a href="#" className="hover:text-text transition">Конфиденциальность</a>
            <a href="#" className="hover:text-text transition">Условия</a>
            <a href="#" className="hover:text-text transition">Поддержка</a>
          </div>
          <p className="text-xs text-text-muted">© 2026 Souldawn. Все права защищены.</p>
        </div>
      </footer>
    </div>
  );
}
