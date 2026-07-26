import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { LogOut, Settings, Shield, Crown, SlidersHorizontal, Gift, Copy, Check } from "lucide-react";
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
  const [distanceMax, setDistanceMax] = useState(100);
  const [savingFilters, setSavingFilters] = useState(false);
  const [filtersSaved, setFiltersSaved] = useState(false);
  const [geoStatus, setGeoStatus] = useState<"idle" | "busy" | "ok" | "fail">("idle");
  const [incognitoBusy, setIncognitoBusy] = useState(false);
  const [incognitoError, setIncognitoError] = useState("");
  const [linkCopied, setLinkCopied] = useState(false);

  const botUsername = import.meta.env.VITE_BOT_USERNAME || "souldawn_dating_bot";

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
      setDistanceMax(data.distance_max ?? 100);
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
      const dist = Math.min(500, Math.max(1, distanceMax || 100));
      await updateMyProfile({
        looking_for: lookingFor, age_min: lo, age_max: hi, distance_max: dist,
      });
      setAgeMin(lo);
      setAgeMax(hi);
      setDistanceMax(dist);
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

  const handleGeolocate = () => {
    if (!navigator.geolocation) {
      setGeoStatus("fail");
      return;
    }
    setGeoStatus("busy");
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          await updateMyProfile({
            latitude: pos.coords.latitude,
            longitude: pos.coords.longitude,
          });
          setGeoStatus("ok");
          setProfile((p) => (p ? { ...p, has_location: true } : p));
        } catch {
          setGeoStatus("fail");
        }
      },
      () => setGeoStatus("fail"),
      { timeout: 10000 }
    );
  };

  const referralLink = profile ? `https://t.me/${botUsername}?start=ref_${profile.id}` : "";

  const copyReferralLink = async () => {
    try {
      await navigator.clipboard.writeText(referralLink);
      setLinkCopied(true);
      setTimeout(() => setLinkCopied(false), 2000);
    } catch {
      // clipboard может быть недоступен вне https — показываем ссылку текстом
      window.prompt("Скопируйте ссылку:", referralLink);
    }
  };

  const toggleIncognito = async () => {
    if (!profile || incognitoBusy) return;
    setIncognitoBusy(true);
    setIncognitoError("");
    try {
      const updated = await updateMyProfile({ is_incognito: !profile.is_incognito });
      setProfile(updated);
    } catch (e: any) {
      setIncognitoError(e.response?.data?.detail || "Не удалось изменить режим");
    } finally {
      setIncognitoBusy(false);
    }
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

        <div className="mb-4">
          <p className="text-xs text-text-muted mb-2">Радиус поиска: {distanceMax} км</p>
          <input
            type="range" min={1} max={500} value={distanceMax}
            onChange={(e) => setDistanceMax(parseInt(e.target.value))}
            className="w-full accent-[var(--color-accent,#e94560)]"
          />
          <button
            onClick={handleGeolocate}
            disabled={geoStatus === "busy"}
            className="mt-2 w-full py-2 bg-bg rounded-full text-sm text-text-muted disabled:opacity-50"
          >
            {geoStatus === "busy" ? "📍 Определяю…"
              : geoStatus === "ok" ? "📍 Местоположение обновлено ✓"
              : geoStatus === "fail" ? "📍 Не удалось — проверьте доступ"
              : profile?.has_location ? "📍 Обновить местоположение"
              : "📍 Включить поиск рядом (геолокация)"}
          </button>
        </div>

        <button
          onClick={saveFilters}
          disabled={savingFilters}
          className="w-full py-2.5 bg-accent text-white rounded-full font-semibold text-sm disabled:opacity-50"
        >
          {filtersSaved ? "✓ Сохранено" : savingFilters ? "Сохраняю…" : "Применить фильтры"}
        </button>
      </div>

      {/* Referral program */}
      <div className="mb-6 p-4 bg-surface rounded-2xl">
        <h3 className="text-sm text-text-muted mb-2 flex items-center gap-2">
          <Gift size={16} className="text-warn" />
          Пригласи друзей — буст анкеты
        </h3>
        {profile?.referral_boost ? (
          <p className="text-sm mb-3">
            🚀 <span className="text-success font-semibold">Буст активен:</span>{" "}
            анкета показывается на {profile?.referral_boost_percent ?? 12}% выше
          </p>
        ) : (
          <>
            <p className="text-sm mb-2">
              Приведи {profile?.referral_target ?? 3} друзей — анкета будет на{" "}
              <span className="text-warn font-semibold">
                +{profile?.referral_boost_percent ?? 12}%
              </span>{" "}
              выше в выдаче
            </p>
            <div className="flex gap-1.5 mb-3">
              {[...Array(profile?.referral_target ?? 3)].map((_, i) => (
                <div
                  key={i}
                  className={`h-1.5 flex-1 rounded-full ${
                    i < (profile?.invited_count ?? 0) ? "bg-warn" : "bg-bg"
                  }`}
                />
              ))}
            </div>
            <p className="text-xs text-text-muted mb-3">
              Прогресс: {profile?.invited_count ?? 0}/{profile?.referral_target ?? 3}
            </p>
          </>
        )}
        <button
          onClick={copyReferralLink}
          className="w-full flex items-center justify-center gap-2 py-2.5 bg-warn/15 text-warn rounded-full text-sm font-medium"
        >
          {linkCopied ? <Check size={16} /> : <Copy size={16} />}
          {linkCopied ? "Скопировано!" : "Скопировать ссылку-приглашение"}
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

        {profile?.is_premium ? (
          <div className="p-4 bg-gradient-to-r from-warn/20 to-accent/20 rounded-2xl">
            <div className="flex items-center gap-3 mb-3">
              <Crown size={20} className="text-warn" />
              <span className="flex-1 font-semibold">Premium активен</span>
              <span className="text-xs px-2 py-1 bg-warn/30 rounded-full">⭐</span>
            </div>
            <button
              onClick={toggleIncognito}
              disabled={incognitoBusy}
              className="w-full flex items-center gap-3 p-3 bg-bg/40 rounded-xl disabled:opacity-50"
            >
              <Shield size={18} className={profile.is_incognito ? "text-success" : "text-text-muted"} />
              <span className="flex-1 text-left text-sm">Инкогнито-режим</span>
              <span
                className={`w-11 h-6 rounded-full relative transition ${
                  profile.is_incognito ? "bg-success" : "bg-surface"
                }`}
              >
                <span
                  className={`absolute top-0.5 w-5 h-5 bg-white rounded-full transition-all ${
                    profile.is_incognito ? "left-[22px]" : "left-0.5"
                  }`}
                />
              </span>
            </button>
            {incognitoError && <p className="mt-2 text-xs text-danger">{incognitoError}</p>}
          </div>
        ) : (
          <a
            href={`https://t.me/${botUsername}?start=premium`}
            target="_blank"
            rel="noreferrer"
            className="w-full flex items-center gap-3 p-4 bg-gradient-to-r from-warn/20 to-accent/20 rounded-2xl hover:opacity-90 transition"
          >
            <Crown size={20} className="text-warn" />
            <span className="flex-1">
              <span className="block font-semibold">Premium за ⭐ Stars</span>
              <span className="block text-xs text-text-muted">
                Инкогнито-режим + буст в выдаче · оформление в Telegram
              </span>
            </span>
          </a>
        )}

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
