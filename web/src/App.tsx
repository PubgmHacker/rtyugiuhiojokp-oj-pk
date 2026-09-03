import { useEffect, useRef, useState, lazy, Suspense } from "react";
import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
  useLocation,
  useNavigate,
  Link,
} from "react-router-dom";
import { motion, AnimatePresence, MotionConfig } from "framer-motion";
import { Flame, MessageCircle, User, Sparkles, LayoutGrid, WifiOff } from "lucide-react";
import ErrorBoundary from "./components/ErrorBoundary";
import PauseBanner from "./components/PauseBanner";
import { useStore } from "./lib/store";
import {
  applyAppearance,
  followTelegramTheme,
  isAppearance,
  loadAppearance,
} from "./lib/appearance";
import { initTelegram } from "./lib/telegram";
import { useTelegramBack } from "./lib/useTelegramBack";
import { initNative, registerPushNotifications } from "./lib/native";
import { startTransactionListener } from "./lib/iap";
import { getBadges, registerDevice } from "./lib/api";
import { haptic } from "./lib/haptics";
import { useT, useЯзыкДокумента, type Ключ } from "./lib/i18n";
import { Spinner } from "./components/ui";

// Discover — стартовый экран, грузим сразу; остальное по требованию,
// иначе весь интерфейс приезжает одним куском при первом открытии
import Discover from "./pages/Discover";
import Login from "./pages/Login";
import { LivingBackground } from "./components/LivingBackground";

const Onboarding = lazy(() => import("./pages/Onboarding"));
const EditProfile = lazy(() => import("./pages/EditProfile"));
const Matches = lazy(() => import("./pages/Matches"));
const Likes = lazy(() => import("./pages/Likes"));
const Chat = lazy(() => import("./pages/Chat"));
const Profile = lazy(() => import("./pages/Profile"));
const Plans = lazy(() => import("./pages/Plans"));
const Reels = lazy(() => import("./pages/Reels"));
const PhotoRatings = lazy(() => import("./pages/PhotoRatings"));
const Rooms = lazy(() => import("./pages/Rooms"));
const Cases = lazy(() => import("./pages/Cases"));
const Tarot = lazy(() => import("./pages/Tarot"));
const VoiceRoulette = lazy(() => import("./pages/VoiceRoulette"));
const More = lazy(() => import("./pages/More"));
const Notifications = lazy(() => import("./pages/Notifications"));
const Habits = lazy(() => import("./pages/Habits"));
const Banned = lazy(() => import("./pages/Banned"));
const AdminDashboard = lazy(() => import("./pages/AdminDashboard"));

// Пять вкладок, как в референсе: Лента, Лайки, Чаты, Ещё, Профиль.
// Знакомства делаются в первых трёх — остальные разделы собраны в «Ещё»,
// иначе навигация конкурирует за внимание с тем, что вообще продаёт продукт.
// Подпись хранится ключом словаря, а не готовой строкой: массив живёт на
// уровне модуля, где языка человека ещё нет, и перевод берётся при отрисовке.
const NAV_ITEMS: { path: string; icon: typeof Flame; label: Ключ }[] = [
  { path: "/discover", icon: Flame, label: "nav.feed" },
  { path: "/likes", icon: Sparkles, label: "nav.likes" },
  { path: "/matches", icon: MessageCircle, label: "nav.chats" },
  { path: "/more", icon: LayoutGrid, label: "nav.more" },
  { path: "/profile", icon: User, label: "nav.profile" },
];

/** Экраны вне вкладок подсвечивают вкладку-родителя: редактирование — «Профиль»,
    переписка — «Чаты», разделы каталога — «Ещё». Иначе пилюля прыгала на «Ленту». */
const РОДИТЕЛЬ_ВКЛАДКИ: readonly [prefix: string, tab: string][] = [
  ["/edit", "/profile"],
  ["/chat", "/matches"],
  ["/plans", "/more"],
  ["/cases", "/more"],
  ["/tarot", "/more"],
  ["/rooms", "/more"],
  ["/habits", "/more"],
  ["/voice", "/more"],
  ["/photo-ratings", "/more"],
  ["/reels", "/more"],
  ["/notifications", "/discover"],
];

function индексВкладки(pathname: string): number {
  const прямой = NAV_ITEMS.findIndex((i) => pathname.startsWith(i.path));
  if (прямой >= 0) return прямой;
  const родитель = РОДИТЕЛЬ_ВКЛАДКИ.find(([prefix]) => pathname.startsWith(prefix));
  return родитель ? NAV_ITEMS.findIndex((i) => i.path === родитель[1]) : -1;
}

/** Геометрия жидкого таб-бара — как в iOS-клиенте Plink */
const БАР = { высота: 64, отступ: 6, пилюля: 50 } as const;
const КРИВАЯ_ПИЛЮЛИ = [0.16, 1, 0.3, 1] as const;

function BottomNav() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const unreadLikes = useStore((s) => s.unreadLikes);
  const unreadMessages = useStore((s) => s.unreadMessages);
  const t = useT();

  const полоса = useRef<HTMLDivElement>(null);
  const [ширина, setШирина] = useState(0);
  const [тянем, setТянем] = useState<number | null>(null);
  const жест = useRef<{ startX: number; moved: boolean; pointerId: number } | null>(null);
  const перетянули = useRef(false);

  const активная = Math.max(0, индексВкладки(pathname));
  const ячейка = ширина > 0 ? (ширина - БАР.отступ * 2) / NAV_ITEMS.length : 0;
  const левый = БАР.отступ;
  const правый = ширина - БАР.отступ - ячейка;

  // Ширина полосы нужна для пилюли в пикселях: transform анимируется без
  // перерасчёта раскладки, а проценты в calc() framer-motion не смешивает
  useEffect(() => {
    const el = полоса.current;
    if (!el) return;
    const мерить = () => setШирина(el.getBoundingClientRect().width);
    мерить();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", мерить);
      return () => window.removeEventListener("resize", мерить);
    }
    const ro = new ResizeObserver(мерить);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Ведение как в Telegram: пилюля идёт за пальцем по полосе, на отпускании
  // прилипает к ближайшей вкладке. Тап без движения остаётся обычным тапом
  // по ссылке — захват указателя не ставим, иначе click уйдёт полосе
  const ближайшая = (clientX: number) => {
    const rect = полоса.current?.getBoundingClientRect();
    if (!rect || ячейка <= 0) return активная;
    const x = clientX - rect.left - БАР.отступ;
    return Math.min(NAV_ITEMS.length - 1, Math.max(0, Math.floor(x / ячейка)));
  };
  const onPointerDown = (e: React.PointerEvent) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    жест.current = { startX: e.clientX, moved: false, pointerId: e.pointerId };
    перетянули.current = false;
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const g = жест.current;
    if (!g || g.pointerId !== e.pointerId || ячейка <= 0) return;
    if (!g.moved && Math.abs(e.clientX - g.startX) < 6) return;
    if (!g.moved) {
      g.moved = true;
      haptic("select");
    }
    const rect = полоса.current!.getBoundingClientRect();
    const x = e.clientX - rect.left - ячейка / 2;
    setТянем(Math.min(правый, Math.max(левый, x)));
  };
  const onPointerEnd = (e: React.PointerEvent) => {
    const g = жест.current;
    if (!g || g.pointerId !== e.pointerId) return;
    жест.current = null;
    if (!g.moved) return;
    перетянули.current = true;
    setТянем(null);
    const idx = ближайшая(e.clientX);
    if (idx !== активная) {
      haptic("select");
      navigate(NAV_ITEMS[idx].path);
    }
  };

  const покойX = левый + активная * ячейка;
  // Пока пилюлю ведут, белой подсвечивается вкладка под ней, а не текущая:
  // палец видит, куда отпустит. aria-current остаётся у настоящей вкладки
  const подсветка =
    тянем !== null && ячейка > 0
      ? Math.min(NAV_ITEMS.length - 1, Math.max(0, Math.round((тянем - левый) / ячейка)))
      : активная;

  return (
    <nav
      aria-label={t("nav.aria")}
      className="fixed bottom-0 left-0 right-0 z-40 safe-x pointer-events-none"
      style={{ paddingBottom: "calc(max(env(safe-area-inset-bottom), 0.5rem) + 2px)" }}
    >
      <div
        ref={полоса}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerEnd}
        onPointerCancel={onPointerEnd}
        className="relative mx-[14px] max-w-[520px] md:mx-auto rounded-full
                   glass-strong pointer-events-auto select-none"
        style={{
          height: БАР.высота,
          padding: `0 ${БАР.отступ}px`,
          touchAction: "none",
        }}
      >
        {/* Пилюля активной вкладки: одна на весь бар, переезжает между
            вкладками по кривой Plink; при ведении — плотнее и чуть крупнее */}
        {ячейка > 0 && (
          <motion.span
            aria-hidden
            className="nav-pill absolute rounded-full"
            data-drag={тянем !== null ? "" : undefined}
            style={{
              top: (БАР.высота - БАР.пилюля) / 2,
              height: БАР.пилюля,
              width: ячейка,
              left: 0,
            }}
            initial={false}
            animate={{ x: тянем ?? покойX, scale: тянем !== null ? 1.07 : 1 }}
            transition={
              тянем !== null
                ? { duration: 0 }
                : { duration: 0.26, ease: [...КРИВАЯ_ПИЛЮЛИ] }
            }
          />
        )}

        <div className="relative flex items-stretch h-full">
          {NAV_ITEMS.map((item, idx) => {
            const isActive = idx === подсветка;
            const badge =
              item.path === "/likes"
                ? unreadLikes
                : item.path === "/matches"
                  ? unreadMessages
                  : 0;

            return (
              <Link
                key={item.path}
                to={item.path}
                draggable={false}
                onClick={(e) => {
                  if (перетянули.current) {
                    e.preventDefault();
                    return;
                  }
                  haptic("select");
                }}
                aria-current={idx === активная ? "page" : undefined}
                className="relative flex-1 flex flex-col items-center justify-center
                           gap-[3px] py-[7px] tap-target"
              >
                <div className="relative">
                  <motion.div
                    className="relative"
                    animate={{ scale: isActive ? 1.04 : 1 }}
                    transition={{ type: "spring", stiffness: 480, damping: 26 }}
                  >
                    <item.icon
                      size={20}
                      strokeWidth={isActive ? 2.3 : 1.9}
                      className={isActive ? "text-white" : "text-text-faint"}
                      fill={isActive && item.path === "/discover" ? "currentColor" : "none"}
                    />
                  </motion.div>

                  {badge > 0 && (
                    <span
                      className="absolute -top-1.5 -right-2.5 min-w-[17px] h-[17px] px-1
                                 rounded-full bg-accent text-white text-[10px] font-bold
                                 flex items-center justify-center shadow-[0_1px_4px_rgb(0_0_0/.35)]"
                    >
                      {badge > 99 ? "99+" : badge}
                    </span>
                  )}
                </div>

                <span
                  className={`text-[10px] font-semibold tracking-[0.01em] leading-none ${
                    isActive ? "text-white" : "text-text-faint"
                  }`}
                >
                  {t(item.label)}
                </span>
              </Link>
            );
          })}
        </div>
      </div>
    </nav>
  );
}

function ScreenFallback() {
  return (
    <div className="flex-1 min-h-[60dvh] flex items-center justify-center text-accent">
      <Spinner size={26} />
    </div>
  );
}

/** Полоса «нет соединения» поверх интерфейса.
 *
 *  Без неё пропажа сети выглядела как поломка приложения: экраны молча
 *  не сохраняли изменения, а единственным сигналом была вибрация, которой
 *  на десктопе и в части WebView нет вовсе. */
function OfflineBanner() {
  const [offline, setOffline] = useState(
    typeof navigator !== "undefined" && navigator.onLine === false
  );

  useEffect(() => {
    const goOffline = () => setOffline(true);
    const goOnline = () => setOffline(false);
    window.addEventListener("offline", goOffline);
    window.addEventListener("online", goOnline);
    return () => {
      window.removeEventListener("offline", goOffline);
      window.removeEventListener("online", goOnline);
    };
  }, []);

  return (
    <AnimatePresence>
      {offline && (
        <motion.div
          role="status"
          initial={{ y: -40, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: -40, opacity: 0 }}
          transition={{ type: "spring", stiffness: 380, damping: 34 }}
          className="fixed top-0 left-0 right-0 z-50 safe-top
                     bg-warn/95 text-bg text-center text-[13px] font-semibold
                     py-1.5 flex items-center justify-center gap-1.5"
        >
          <WifiOff size={14} />
          Нет соединения — изменения не сохранятся
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** Корневые экраны: с них назад некуда, кнопка в шапке была бы обманом. */
function корневой(pathname: string): boolean {
  const главный =
    localStorage.getItem("sd_main_screen") === "reels" ? "/reels" : "/discover";
  return (
    pathname === "/" ||
    pathname === главный ||
    pathname === "/login" ||
    // Онбординг и экран блокировки водят кнопкой сами: в первом «назад» — это
    // предыдущий шаг анкеты, из второго выходить некуда
    pathname === "/onboarding" ||
    pathname === "/banned" ||
    NAV_ITEMS.some((i) => i.path === pathname)
  );
}

/**
 * Нативная кнопка «назад» Telegram на вложенных экранах.
 *
 * Одним местом на всё приложение, а не по экрану: внутри Telegram нет ни
 * системного жеста «назад», ни кнопки браузера, а своя стрелка нарисована не
 * везде — из чата (там нижняя навигация скрыта) выйти было нечем, кроме
 * закрытия Mini App. Вне Telegram хук — no-op.
 */
function TelegramBack() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  useTelegramBack(корневой(pathname) ? null : () => navigate(-1));
  return null;
}

function Protected({ children, nav = true }: { children: React.ReactNode; nav?: boolean }) {
  const token = useStore((s) => s.token);
  const { pathname } = useLocation();
  if (!token) return <Navigate to="/login" replace />;
  return (
    <div className={`min-h-screen-safe ${nav ? "pb-nav" : ""}`}>
      {/* Своя граница на каждый экран, а не одна на всё приложение: упавший
          экран не роняет оболочку — таб-бар живёт, и человек уходит на другую
          вкладку. Ключ-маршрут перемонтирует границу при переходе, иначе React
          переиспользует тот же экземпляр (все Route отдают <Protected> в одной
          позиции дерева) и ошибка висела бы на следующем экране */}
      <ErrorBoundary key={pathname} compact>
        <Suspense fallback={<ScreenFallback />}>{children}</Suspense>
      </ErrorBoundary>
      {/* Пауза скрывает анкету отовсюду, поэтому и предупреждение живёт
          в оболочке, а не на одном экране: с какого бы места человек ни
          начал, он узнаёт, что его не видно. Плавающий пузырь — чтобы не
          трогать вёрстку экранов с фиксированной высотой (дека) */}
      <PauseBanner />
      {nav && <BottomNav />}
    </div>
  );
}

export default function App() {
  const { token, user, isOnboarded } = useStore();

  // `<html lang>` держим в согласии с выбором языка. Это не косметика: от
  // атрибута зависят экранные читалки (турецкий текст, прочитанный английскими
  // правилами, — каша), переносы слов и подбор шрифта для 中文. В index.html
  // зашит `ru` — верный для большинства и для первого кадра, дальше правим.
  useЯзыкДокумента();

  useEffect(() => {
    // Профиль из localStorage гидрируется синхронно в store.ts: здесь его
    // читать поздно — редирект /login уже отработал по первому рендеру.
    initTelegram();
    initNative();
    // Тему Telegram догоняем здесь, а не в main.tsx: SDK приезжает асинхронно
    // и на первом кадре colorScheme ещё неизвестен (см. followTelegramTheme).
    return followTelegramTheme();
  }, []);

  // Разрешение на уведомления спрашиваем только после входа: системный
  // запрос на экране логина выглядит необъяснимо, и его чаще отклоняют.
  useEffect(() => {
    if (!token) return;
    registerPushNotifications((deviceToken, platform) =>
      registerDevice(deviceToken, platform).catch(() => {
        // Токен пришлём при следующем запуске — молчим, чтобы не пугать
      })
    );
  }, [token]);

  // Схема из анкеты догоняет локальную: initAppearance() в main.tsx уже
  // показал сохранённую на этом устройстве, здесь выравниваем по серверу,
  // чтобы выбор с другого телефона доехал.
  useEffect(() => {
    const key = user?.app_theme;
    if (isAppearance(key) && key !== loadAppearance()) applyAppearance(key);
  }, [user?.app_theme]);

  // Продления подписки и покупки с другого устройства приходят только сюда.
  // Без этого слушателя сервер не узнает о продлении и Premium погаснет
  // у человека, который продолжает платить.
  useEffect(() => {
    if (!token) return;
    startTransactionListener();
  }, [token]);

  // Бейджи таббара — при входе и каждом возвращении в приложение. До этого
  // цифры появлялись только после захода на сам экран, и вкладка с новым
  // сообщением выглядела пустой. Экраны Лайков и Чатов дальше уточняют
  // счётчики сами по мере чтения.
  useEffect(() => {
    if (!token) return;
    const тянуть = () => {
      getBadges()
        .then((b) => {
          const s = useStore.getState();
          s.setUnreadMessages(b.messages);
          s.setUnreadLikes(b.likes);
          s.setUnreadNotifications(b.notifications);
        })
        .catch(() => {
          // Бейдж — украшение: без сети он просто не обновится
        });
    };
    тянуть();
    const onFocus = () => document.visibilityState === "visible" && тянуть();
    document.addEventListener("visibilitychange", onFocus);
    window.addEventListener("focus", onFocus);
    return () => {
      document.removeEventListener("visibilitychange", onFocus);
      window.removeEventListener("focus", onFocus);
    };
  }, [token]);

  return (
    // reducedMotion="user": системная настройка «Уменьшить движение» гасит
    // transform-анимации Framer (пружины, вылеты карточек), оставляя opacity.
    // CSS-ветка в globals.css её не покрывает — Framer анимирует из JS.
    <MotionConfig reducedMotion="user">
    <BrowserRouter>
      {/* Орбы схемы под всеми экранами, включая вход: атмосфера — часть
          продукта, а не награда за авторизацию */}
      <LivingBackground />
      <OfflineBanner />
      <TelegramBack />
      {/* Исключение в любом экране не должно оставлять белый экран без выхода */}
      <ErrorBoundary>
      <Suspense fallback={<ScreenFallback />}>
        <Routes>
          {/* Публичный лендинг — отдельный статический сайт (landing/),
              внутри приложения корень ведёт сразу в продукт */}
          <Route
            path="/"
            element={<Navigate to={token ? (localStorage.getItem("sd_main_screen") === "reels" ? "/reels" : "/discover") : "/login"} replace />}
          />
          <Route
            path="/login"
            element={
              token ? (
                <Navigate to={isOnboarded ? (localStorage.getItem("sd_main_screen") === "reels" ? "/reels" : "/discover") : "/onboarding"} replace />
              ) : (
                <Login />
              )
            }
          />

          {/* Экран блокировки — вне Protected: он обязан открываться без
              единого запроса к API, иначе перехватчик 403 в api.ts зациклит
              редирект /banned → /discover → 403 → /banned */}
          <Route path="/banned" element={<Banned />} />

          <Route path="/onboarding" element={<Protected nav={false}><Onboarding /></Protected>} />
          {/* Точечная правка анкеты: свой экран, чтобы не гонять человека
              одиннадцатью шагами онбординга ради одного поля */}
          <Route path="/edit" element={<Protected nav={false}><EditProfile /></Protected>} />
          <Route path="/discover" element={<Protected><Discover /></Protected>} />
          <Route path="/matches" element={<Protected><Matches /></Protected>} />
          <Route path="/likes" element={<Protected><Likes /></Protected>} />
          {/* В чате нижняя навигация мешает полю ввода */}
          <Route path="/chat/:matchId" element={<Protected nav={false}><Chat /></Protected>} />
          <Route path="/plans" element={<Protected><Plans /></Protected>} />
          <Route path="/notifications" element={<Protected><Notifications /></Protected>} />
          {/* Лента роликов сама во весь экран — своя нижняя навигация остаётся */}
          <Route path="/more" element={<Protected><More /></Protected>} />
          <Route path="/reels" element={<Protected><Reels /></Protected>} />
          <Route path="/photo-ratings" element={<Protected><PhotoRatings /></Protected>} />
          <Route path="/rooms" element={<Protected><Rooms /></Protected>} />
          <Route path="/cases" element={<Protected><Cases /></Protected>} />
          <Route path="/habits" element={<Protected><Habits /></Protected>} />
          <Route path="/tarot" element={<Protected><Tarot /></Protected>} />
          <Route path="/voice" element={<Protected><VoiceRoulette /></Protected>} />
          <Route path="/profile" element={<Protected><Profile /></Protected>} />
          <Route path="/admin" element={<Protected nav={false}><AdminDashboard /></Protected>} />

          <Route path="*" element={<Navigate to={token ? "/discover" : "/login"} replace />} />
        </Routes>
      </Suspense>
      </ErrorBoundary>
    </BrowserRouter>
    </MotionConfig>
  );
}
