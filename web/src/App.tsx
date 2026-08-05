import { useEffect, useState, lazy, Suspense } from "react";
import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
  useLocation,
  Link,
} from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Flame, MessageCircle, User, Sparkles, LayoutGrid, WifiOff } from "lucide-react";
import { useStore } from "./lib/store";
import { initTelegram } from "./lib/telegram";
import { initNative, registerPushNotifications } from "./lib/native";
import { startTransactionListener } from "./lib/iap";
import { registerDevice } from "./lib/api";
import { haptic } from "./lib/haptics";
import { Spinner } from "./components/ui";

// Discover — стартовый экран, грузим сразу; остальное по требованию,
// иначе весь интерфейс приезжает одним куском при первом открытии
import Discover from "./pages/Discover";
import Login from "./pages/Login";

const Onboarding = lazy(() => import("./pages/Onboarding"));
const Matches = lazy(() => import("./pages/Matches"));
const Likes = lazy(() => import("./pages/Likes"));
const Chat = lazy(() => import("./pages/Chat"));
const Profile = lazy(() => import("./pages/Profile"));
const Plans = lazy(() => import("./pages/Plans"));
const Reels = lazy(() => import("./pages/Reels"));
const PhotoRatings = lazy(() => import("./pages/PhotoRatings"));
const Rooms = lazy(() => import("./pages/Rooms"));
const Cases = lazy(() => import("./pages/Cases"));
const VoiceRoulette = lazy(() => import("./pages/VoiceRoulette"));
const More = lazy(() => import("./pages/More"));
const AdminDashboard = lazy(() => import("./pages/AdminDashboard"));

// Пять вкладок, как в референсе: Лента, Лайки, Чаты, Ещё, Профиль.
// Знакомства делаются в первых трёх — остальные разделы собраны в «Ещё»,
// иначе навигация конкурирует за внимание с тем, что вообще продаёт продукт.
const NAV_ITEMS = [
  { path: "/discover", icon: Flame, label: "Лента" },
  { path: "/likes", icon: Sparkles, label: "Лайки" },
  { path: "/matches", icon: MessageCircle, label: "Чаты" },
  { path: "/more", icon: LayoutGrid, label: "Ещё" },
  { path: "/profile", icon: User, label: "Профиль" },
];

function BottomNav() {
  const { pathname } = useLocation();
  const unreadLikes = useStore((s) => s.unreadLikes);

  return (
    <nav
      aria-label="Основная навигация"
      className="fixed bottom-0 left-0 right-0 z-40 chrome
                 border-t border-hairline/70 safe-bottom safe-x"
    >
      <div className="flex items-stretch justify-around max-w-[520px] mx-auto">
        {NAV_ITEMS.map((item) => {
          const isActive = pathname.startsWith(item.path);
          const badge = item.path === "/likes" ? unreadLikes : 0;

          return (
            <Link
              key={item.path}
              to={item.path}
              onClick={() => haptic("select")}
              aria-current={isActive ? "page" : undefined}
              className="relative flex-1 flex flex-col items-center justify-center
                         gap-1 pt-2.5 pb-1.5 tap-target"
            >
              {isActive && (
                <motion.span
                  layoutId="nav-indicator"
                  className="absolute top-0 h-[2.5px] w-8 rounded-full bg-dawn"
                  transition={{ type: "spring", stiffness: 420, damping: 34 }}
                />
              )}

              <div className="relative">
                <motion.div
                  animate={{ scale: isActive ? 1.06 : 1, y: isActive ? -1 : 0 }}
                  transition={{ type: "spring", stiffness: 480, damping: 26 }}
                >
                  <item.icon
                    size={23}
                    strokeWidth={isActive ? 2.4 : 1.9}
                    className={isActive ? "text-accent" : "text-text-faint"}
                    fill={isActive && item.path === "/discover" ? "currentColor" : "none"}
                  />
                </motion.div>

                {badge > 0 && (
                  <span
                    className="absolute -top-1 -right-2 min-w-[17px] h-[17px] px-1
                               rounded-full bg-dawn text-white text-[10px] font-bold
                               flex items-center justify-center"
                  >
                    {badge > 99 ? "99+" : badge}
                  </span>
                )}
              </div>

              <span
                className={`text-[10.5px] font-medium tracking-[-0.01em] ${
                  isActive ? "text-accent" : "text-text-faint"
                }`}
              >
                {item.label}
              </span>
            </Link>
          );
        })}
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

function Protected({ children, nav = true }: { children: React.ReactNode; nav?: boolean }) {
  const token = useStore((s) => s.token);
  if (!token) return <Navigate to="/login" replace />;
  return (
    <div className={`min-h-screen-safe ${nav ? "pb-[68px]" : ""}`}>
      <Suspense fallback={<ScreenFallback />}>{children}</Suspense>
      {nav && <BottomNav />}
    </div>
  );
}

export default function App() {
  const { token, setUser, isOnboarded } = useStore();

  useEffect(() => {
    initTelegram();
    initNative();
    const saved = localStorage.getItem("sd_user");
    if (saved) {
      try {
        setUser(JSON.parse(saved));
      } catch {
        localStorage.removeItem("sd_user");
      }
    }
  }, [setUser]);

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

  // Продления подписки и покупки с другого устройства приходят только сюда.
  // Без этого слушателя сервер не узнает о продлении и Premium погаснет
  // у человека, который продолжает платить.
  useEffect(() => {
    if (!token) return;
    startTransactionListener();
  }, [token]);

  return (
    <BrowserRouter>
      <OfflineBanner />
      <Suspense fallback={<ScreenFallback />}>
        <Routes>
          {/* Публичный лендинг — отдельный статический сайт (landing/),
              внутри приложения корень ведёт сразу в продукт */}
          <Route
            path="/"
            element={<Navigate to={token ? "/discover" : "/login"} replace />}
          />
          <Route
            path="/login"
            element={
              token ? (
                <Navigate to={isOnboarded ? "/discover" : "/onboarding"} replace />
              ) : (
                <Login />
              )
            }
          />

          <Route path="/onboarding" element={<Protected nav={false}><Onboarding /></Protected>} />
          <Route path="/discover" element={<Protected><Discover /></Protected>} />
          <Route path="/matches" element={<Protected><Matches /></Protected>} />
          <Route path="/likes" element={<Protected><Likes /></Protected>} />
          {/* В чате нижняя навигация мешает полю ввода */}
          <Route path="/chat/:matchId" element={<Protected nav={false}><Chat /></Protected>} />
          <Route path="/plans" element={<Protected><Plans /></Protected>} />
          {/* Лента роликов сама во весь экран — своя нижняя навигация остаётся */}
          <Route path="/more" element={<Protected><More /></Protected>} />
          <Route path="/reels" element={<Protected><Reels /></Protected>} />
          <Route path="/photo-ratings" element={<Protected><PhotoRatings /></Protected>} />
          <Route path="/rooms" element={<Protected><Rooms /></Protected>} />
          <Route path="/cases" element={<Protected><Cases /></Protected>} />
          <Route path="/voice" element={<Protected><VoiceRoulette /></Protected>} />
          <Route path="/profile" element={<Protected><Profile /></Protected>} />
          <Route path="/admin" element={<Protected nav={false}><AdminDashboard /></Protected>} />

          <Route path="*" element={<Navigate to={token ? "/discover" : "/login"} replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
