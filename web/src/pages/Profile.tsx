import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { LogOut, Settings, Shield, Crown } from "lucide-react";
import { getMyProfile, type UserProfile } from "../lib/api";
import { useStore } from "../lib/store";

export default function Profile() {
  const navigate = useNavigate();
  const { logout } = useStore();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadProfile();
  }, []);

  const loadProfile = async () => {
    try {
      const data = await getMyProfile();
      setProfile(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
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
