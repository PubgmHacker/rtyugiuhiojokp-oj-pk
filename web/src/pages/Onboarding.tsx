import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { Camera, X, Plus } from "lucide-react";
import { updateMyProfile, uploadPhoto } from "../lib/api";
import { useStore } from "../lib/store";
import { hapticFeedback } from "../lib/telegram";

const INTERESTS_PRESETS = [
  "Путешествия", "Спорт", "Кино", "Музыка", "Готовка", "Чтение",
  "Фотография", "Танцы", "Йога", "Игры", "Искусство", "Природа",
  "Кофе", "Вино", "Технологии", "Мода", "Авто", "Животные",
];

export default function Onboarding() {
  const navigate = useNavigate();
  const { user, setUser } = useStore();

  const [step, setStep] = useState(0);
  const [displayName, setDisplayName] = useState(user?.display_name || "");
  const [gender, setGender] = useState(user?.gender || "");
  const [birthYear, setBirthYear] = useState("");
  const [city, setCity] = useState(user?.city || "");
  const [bio, setBio] = useState(user?.bio || "");
  const [lookingFor, setLookingFor] = useState(user?.looking_for || "");
  const [interests, setInterests] = useState<string[]>(user?.interests || []);
  const [photos, setPhotos] = useState<string[]>(user?.photos || []);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

  const totalSteps = 7;

  const handlePhotoUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    if (photos.length >= 6) return;

    setUploading(true);
    try {
      const file = files[0];
      const result = await uploadPhoto(file);
      setPhotos([...photos, result.url]);
      hapticFeedback("success");
    } catch (e: any) {
      setError(e.response?.data?.detail || "Ошибка загрузки фото");
    } finally {
      setUploading(false);
    }
  };

  const toggleInterest = (interest: string) => {
    if (interests.includes(interest)) {
      setInterests(interests.filter((i) => i !== interest));
    } else if (interests.length < 10) {
      setInterests([...interests, interest]);
    }
  };

  const handleNext = () => {
    setError("");
    if (step < totalSteps - 1) {
      hapticFeedback("light");
      setStep(step + 1);
    } else {
      handleFinish();
    }
  };

  const handleFinish = async () => {
    try {
      const birthDate = birthYear ? `${birthYear}-01-01` : undefined;
      const updated = await updateMyProfile({
        display_name: displayName,
        gender,
        birth_date: birthDate,
        city,
        bio,
        looking_for: lookingFor,
        interests,
        photos,
      });
      setUser(updated);
      hapticFeedback("success");
      navigate("/discover");
    } catch (e: any) {
      setError(e.response?.data?.detail || "Ошибка сохранения");
    }
  };

  const canProceed = () => {
    switch (step) {
      case 0: return displayName.trim().length > 0;
      case 1: return !!gender;
      case 2: return birthYear && parseInt(birthYear) >= 1920 && parseInt(birthYear) <= 2010;
      case 3: return city.trim().length > 0;
      case 4: return !!lookingFor;
      case 5: return true; // bio optional
      case 6: return photos.length > 0;
      default: return true;
    }
  };

  return (
    <div className="min-h-screen flex flex-col max-w-md mx-auto p-6">
      {/* Progress bar */}
      <div className="flex gap-1.5 mb-8 mt-4">
        {[...Array(totalSteps)].map((_, i) => (
          <div
            key={i}
            className={`h-1 flex-1 rounded-full transition-all ${
              i <= step ? "bg-accent" : "bg-surface"
            }`}
          />
        ))}
      </div>

      <div className="flex-1">
        <AnimatePresence mode="wait">
          <motion.div
            key={step}
            initial={{ opacity: 0, x: 30 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -30 }}
            transition={{ duration: 0.2 }}
          >
            {step === 0 && (
              <StepContainer title="Как тебя зовут?" subtitle="Это имя увидят другие пользователи">
                <input
                  type="text"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="Ваше имя"
                  maxLength={50}
                  autoFocus
                  className="w-full px-5 py-4 bg-surface rounded-2xl text-lg outline-none focus:ring-2 focus:ring-accent"
                />
              </StepContainer>
            )}

            {step === 1 && (
              <StepContainer title="Кто ты?" subtitle="Это поможет подобрать подходящие мэтчи">
                <div className="grid grid-cols-3 gap-3">
                  {[
                    { val: "male", label: "👨 Мужчина" },
                    { val: "female", label: "👩 Женщина" },
                    { val: "other", label: "🧑 Другое" },
                  ].map((g) => (
                    <button
                      key={g.val}
                      onClick={() => setGender(g.val)}
                      className={`py-4 rounded-2xl font-medium transition ${
                        gender === g.val
                          ? "bg-accent text-white"
                          : "bg-surface text-text-muted"
                      }`}
                    >
                      {g.label}
                    </button>
                  ))}
                </div>
              </StepContainer>
            )}

            {step === 2 && (
              <StepContainer title="Когда ты родился?" subtitle="Только год, для начала">
                <input
                  type="number"
                  value={birthYear}
                  onChange={(e) => setBirthYear(e.target.value)}
                  placeholder="1995"
                  min="1920"
                  max="2010"
                  autoFocus
                  className="w-full px-5 py-4 bg-surface rounded-2xl text-2xl text-center outline-none focus:ring-2 focus:ring-accent"
                />
              </StepContainer>
            )}

            {step === 3 && (
              <StepContainer title="Где ты живешь?" subtitle="Для поиска людей поблизости">
                <input
                  type="text"
                  value={city}
                  onChange={(e) => setCity(e.target.value)}
                  placeholder="Москва"
                  autoFocus
                  className="w-full px-5 py-4 bg-surface rounded-2xl text-lg outline-none focus:ring-2 focus:ring-accent"
                />
              </StepContainer>
            )}

            {step === 4 && (
              <StepContainer title="Кого ищешь?" subtitle="Мы покажем нужные анкеты">
                <div className="grid grid-cols-1 gap-3">
                  {[
                    { val: "female", label: "👩 Женщин" },
                    { val: "male", label: "👨 Мужчин" },
                    { val: "any", label: "💞 Всех" },
                  ].map((g) => (
                    <button
                      key={g.val}
                      onClick={() => setLookingFor(g.val)}
                      className={`py-4 rounded-2xl font-medium transition ${
                        lookingFor === g.val
                          ? "bg-accent text-white"
                          : "bg-surface text-text-muted"
                      }`}
                    >
                      {g.label}
                    </button>
                  ))}
                </div>
              </StepContainer>
            )}

            {step === 5 && (
              <StepContainer title="Расскажи о себе" subtitle="До 500 символов (можно пропустить)">
                <textarea
                  value={bio}
                  onChange={(e) => setBio(e.target.value.slice(0, 500))}
                  placeholder="Люблю путешествия, кофе по утрам и хорошие книги..."
                  rows={5}
                  className="w-full px-5 py-4 bg-surface rounded-2xl outline-none focus:ring-2 focus:ring-accent resize-none"
                />
                <p className="text-right text-sm text-text-muted mt-1">{bio.length}/500</p>

                {/* Interest chips */}
                <div className="mt-4">
                  <p className="text-sm text-text-muted mb-2">Интересы ({interests.length}/10):</p>
                  <div className="flex flex-wrap gap-2">
                    {INTERESTS_PRESETS.map((interest) => (
                      <button
                        key={interest}
                        onClick={() => toggleInterest(interest)}
                        className={`px-3 py-1.5 rounded-full text-sm transition ${
                          interests.includes(interest)
                            ? "bg-accent text-white"
                            : "bg-surface text-text-muted"
                        }`}
                      >
                        {interest}
                      </button>
                    ))}
                  </div>
                </div>
              </StepContainer>
            )}

            {step === 6 && (
              <StepContainer title="Добавь фото" subtitle="До 6 фото. Минимум 1.">
                <div className="grid grid-cols-3 gap-3">
                  {[...Array(6)].map((_, i) => (
                    <div key={i} className="aspect-square">
                      {photos[i] ? (
                        <div className="relative w-full h-full rounded-2xl overflow-hidden group">
                          <img src={photos[i]} alt="" className="w-full h-full object-cover" />
                          <button
                            onClick={() => setPhotos(photos.filter((_, idx) => idx !== i))}
                            className="absolute top-1 right-1 w-6 h-6 bg-black/60 rounded-full flex items-center justify-center"
                          >
                            <X size={14} />
                          </button>
                        </div>
                      ) : i === photos.length ? (
                        <label className="w-full h-full rounded-2xl border-2 border-dashed border-white/20 flex items-center justify-center cursor-pointer hover:border-accent transition bg-surface">
                          {uploading ? (
                            <span className="text-xs text-text-muted">...</span>
                          ) : (
                            <Camera size={24} className="text-text-muted" />
                          )}
                          <input
                            type="file"
                            accept="image/*"
                            onChange={handlePhotoUpload}
                            className="hidden"
                            disabled={uploading}
                          />
                        </label>
                      ) : (
                        <div className="w-full h-full rounded-2xl border-2 border-dashed border-white/5 bg-surface/50" />
                      )}
                    </div>
                  ))}
                </div>
              </StepContainer>
            )}
          </motion.div>
        </AnimatePresence>
      </div>

      {error && (
        <div className="mb-3 px-4 py-2 bg-danger/20 border border-danger/40 rounded-xl text-danger text-sm">
          {error}
        </div>
      )}

      <div className="flex gap-3 mt-4">
        {step > 0 && (
          <button
            onClick={() => setStep(step - 1)}
            className="px-6 py-3 bg-surface text-text-muted rounded-full font-medium"
          >
            Назад
          </button>
        )}
        <button
          onClick={handleNext}
          disabled={!canProceed()}
          className="flex-1 py-3 bg-gradient-to-r from-accent to-warn text-white font-bold rounded-full disabled:opacity-40"
        >
          {step === totalSteps - 1 ? "Готово!" : "Далее"}
        </button>
      </div>
    </div>
  );
}

function StepContainer({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div>
      <h2 className="text-2xl font-bold mb-1">{title}</h2>
      {subtitle && <p className="text-text-muted mb-6">{subtitle}</p>}
      {children}
    </div>
  );
}
