import { useEffect } from "react";
import { BrowserRouter, Routes, Route, Navigate, useLocation, Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Flame, MessageCircle, User } from "lucide-react";
import { useStore } from "./lib/store";
import { initTelegram } from "./lib/telegram";
import Login from "./pages/Login";
import Onboarding from "./pages/Onboarding";
import Discover from "./pages/Discover";
import Matches from "./pages/Matches";
import Chat from "./pages/Chat";
import Profile from "./pages/Profile";
import AdminDashboard from "./pages/AdminDashboard";
import Landing from "./pages/Landing";

function BottomNav() {
  const location = useLocation();
  const currentPath = location.pathname;

  const navItems = [
    { path: "/discover", icon: Flame, label: "Поиск" },
    { path: "/matches", icon: MessageCircle, label: "Мэтчи" },
    { path: "/profile", icon: User, label: "Профиль" },
  ];

  return (
    <nav className="fixed bottom-0 left-0 right-0 flex items-center justify-around py-2 bg-bg/95 backdrop-blur-lg border-t border-surface safe-bottom z-40">
      {navItems.map((item) => {
        const isActive = currentPath.startsWith(item.path);
        return (
          <Link
            key={item.path}
            to={item.path}
            className="flex flex-col items-center gap-0.5 px-6 py-1 transition"
          >
            <motion.div animate={isActive ? { scale: 1.1 } : { scale: 1 }}>
              <item.icon
                size={24}
                className={isActive ? "text-accent" : "text-text-muted"}
                fill={isActive && item.path === "/discover" ? "currentColor" : "none"}
              />
            </motion.div>
            <span className={`text-xs ${isActive ? "text-accent font-medium" : "text-text-muted"}`}>
              {item.label}
            </span>
          </Link>
        );
      })}
    </nav>
  );
}

function ProtectedLayout({ children }: { children: React.ReactNode }) {
  const { token } = useStore();
  if (!token) return <Navigate to="/login" replace />;
  return (
    <div className="min-h-screen pb-20">
      {children}
      <BottomNav />
    </div>
  );
}

export default function App() {
  const { token, setUser } = useStore();

  useEffect(() => {
    initTelegram();
    // Restore user from localStorage
    const saved = localStorage.getItem("sd_user");
    if (saved) {
      try {
        setUser(JSON.parse(saved));
      } catch {
        localStorage.removeItem("sd_user");
      }
    }
  }, []);

  return (
    <BrowserRouter>
      <Routes>
        {/* Public */}
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={token ? <Navigate to="/discover" /> : <Login />} />

        {/* Protected */}
        <Route path="/onboarding" element={<ProtectedLayout><Onboarding /></ProtectedLayout>} />
        <Route path="/discover" element={<ProtectedLayout><Discover /></ProtectedLayout>} />
        <Route path="/matches" element={<ProtectedLayout><Matches /></ProtectedLayout>} />
        <Route path="/chat/:matchId" element={<ProtectedLayout><Chat /></ProtectedLayout>} />
        <Route path="/profile" element={<ProtectedLayout><Profile /></ProtectedLayout>} />

        {/* Admin */}
        <Route path="/admin" element={<ProtectedLayout><AdminDashboard /></ProtectedLayout>} />

        {/* Redirect */}
        <Route path="*" element={<Navigate to={token ? "/discover" : "/"} />} />
      </Routes>
    </BrowserRouter>
  );
}
