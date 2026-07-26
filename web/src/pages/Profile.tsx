import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { LogOut, Settings, Shield, Crown, SlidersHorizontal } from "lucide-react";
import { getMyProfile, updateMyProfile, type UserProfile } from "../lib/api";
import { useStore } from "../lib/store";

export default function Profile() {
  const navigate = useNavigate();
  const { logout, setDeck } = useStore();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [lookingFor, setLookingFor] = useState("any");
  const [ageMin, setAgeMin] = useState(18);
  const [ageMax, setAgeMax] = useState(99);
  const [savingFilters, setSavingFilters] = useState(false);
  const [filtersSaved, setFiltersSaved] = useState(false);

  useEffect(() => {
    loadProfile();
  }, []);

  const loadProfile = async () => {
    try {
      const data = await getMyProfile();
      setProfile(data);
      setLookingFor(data.looking_for || "any");
      setAgeMin(data.age_min ?? 18);
      setAgeMax(data.age_max ?? 99);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const saveFilters = async () => {
    setSavingFilters(true);
    setFiltersSaved(false);
    try {
      const clamp = (v: number) => Math.min(99, Math.max(18, v || 18));
      const lo = clamp(Math.min(ageMin, ageMax));
      const hi = clamp(Math.max(ageMin, ageMax));
      await updateMyProfile({ looking_for: lookingFor, age_min: lo, age_max: hi });
      setAgeMin(lo);
      setAgeMax(hi);
      setDeck([]); // сбрасываем деку, чтобы фильтры применились сразу
      setFiltersSaved(true);
      setTimeout(() => setFiltersSaved(false), 2000);
    } catch (e) {
      console.error(e);
    } finally {
      setSavingFilters(false);
    }
  };

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-accent" />
      </div>
    );
  }

  return (
    <div className="min-h-screen max-w-md mx-auto p-4">
      {/* Profile header */}
      <div className="text-center mb-8">
        <div className="relative inline-block mb-4">
          {profile?.photos?.[0] ? (
            <img
              src={profile.photos[0]}
              alt={profile.display_name}
              className="w-28 h-28 rounded-full object-cover border-4 border-accent/30"
            />
          ) : (
            <div className="w-28 h-28 rounded-full bg-surface flex items-center justify-center border-4 border-accent/30">
              <span className="text-4xl">👤</span>
            </div>
          )}
          {profile?.is_verified && (
            <div className="absolute bottom-0 right-0 w-8 h-8 bg-success rounded-full border-4 border-bg flex items-center justify-center">
              ✓
            </div>
          )}
        </div>

        <h1 className="text-2xl font-bold">{profile?.display_name || "Аноним"}</h1>
        {profile?.age && <p className="text-text-muted">{profile.age} лет</p>}
        {profile?.city && <p className="text-text-muted text-sm">📍 {profile.city}</p>}
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-3 mb-6">
        <StatCard label="Фото" value={profile?.photos?.length || 0} />
        <StatCard label="Интересы" value={profile?.interests?.length || 0} />
        <StatCard label="Статус" value={profile?.is_verified ? "✓" : "—"} />
      </div>

      {/* Bio */}
      {profile?.bio && (
        <div className="mb-6 p-4 bg-surface rounded-2xl">
          <h3 className="text-sm text-text-muted mb-2">О себе</h3>
          <p>{profile.bio}</p>
        </div>
      )}

      {/* Interests */}
      {profile?.interests && profile.interests.length > 0 && (
        <div className="mb-6">
          <h3 className="text-sm text-text-muted mb-2">Интересы</h3>
          <div className="flex flex-wrap gap-2">
            {profile.interests.map((interest, i) => (
              <span key={i} className="px-3 py-1.5 bg-surface rounded-full text-sm">
                {interest}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Search filters */}
      <div className="mb-6 p-4 bg-surface rounded-2xl">
        <h3 className="text-sm text-text-muted mb-3 flex items-center gap-2">
          <SlidersHorizontal size={16} className="text-accent" />
          Настройки поиска
        </h3>

        <div className="mb-3">
          <p className="text-xs text-text-muted mb-2">Кого показывать</p>
          <div className="flex gap-2">
            {[
              { value: "female", label: "Девушек" },
              { value: "male", label: "Парней" },
              { value: "any", label: "Всех" },
            ].map((opt) => (
              <button
                key={opt.value}
                onClick={() => setLookingFor(opt.value)}
                className={`flex-1 py-2 rounded-full text-sm font-medium transition ${
                  lookingFor === opt.value
                    ? "bg-accent text-white"
                    : "bg-bg text-text-muted"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        <div className="mb-4">
          <p className="text-xs text-text-muted mb-2">
            Возраст: {Math.min(ageMin, ageMax)}–{Math.max(ageMin, ageMax)}
          </p>
          <div className="flex items-center gap-3">
            <input
              type="number" min={18} max={99} value={ageMin}
              onChange={(e) => setAgeMin(parseInt(e.target.value) || 18)}
              className="w-20 px-3 py-2 bg-bg rounded-xl text-center outline-none focus:ring-2 focus:ring-accent"
            />
            <span className="text-text-muted">—</span>
            <input
              type="number" min={18} max={99} value={ageMax}
              onChange={(e) => setAgeMax(parseInt(e.target.value) || 99)}
              className="w-20 px-3 py-2 bg-bg rounded-xl text-center outline-none focus:ring-2 focus:ring-accent"
            />
          </div>
        </div>

        <button
          onClick={saveFilters}
          disabled={savingFilters}
          className="w-full py-2.5 bg-accent text-white rounded-full font-semibold text-sm disabled:opacity-50"
        >
          {filtersSaved ? "✓ Сохранено" : savingFilters ? "Сохраняю…" : "Применить фильтры"}
        </button>
      </div>

      {/* Menu items */}
      <div className="space-y-2">
        <button
          onClick={() => navigate("/onboarding")}
          className="w-full flex items-center gap-3 p-4 bg-surface rounded-2xl hover:bg-surface/80 transition"
        >
          <Settings size={20} className="text-accent" />
          <span>Редактировать анкету</span>
        </button>

        <button className="w-full flex items-center gap-3 p-4 bg-gradient-to-r from-warn/20 to-accent/20 rounded-2xl">
          <Crown size={20} className="text-warn" />
          <span className="flex-1 text-left">Premium</span>
          <span className="text-xs text-text-muted">Скоро</span>
        </button>

        <button className="w-full flex items-center gap-3 p-4 bg-surface rounded-2xl hover:bg-surface/80 transition">
          <Shield size={20} className="text-success" />
          <span>Конфиденциальность</span>
        </button>

        <button
          onClick={handleLogout}
          className="w-full flex items-center gap-3 p-4 bg-danger/10 rounded-2xl hover:bg-danger/20 transition text-danger"
        >
          <LogOut size={20} />
          <span>Выйти</span>
        </button>
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="text-center p-4 bg-surface rounded-2xl">
      <p className="text-2xl font-bold">{value}</p>
      <p className="text-xs text-text-muted">{label}</p>
    </div>
  );
}
