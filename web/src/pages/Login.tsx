import { useState, useEffect, useCallback, useRef } from "react";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import {
  authWithTelegram,
  authDev,
  authWithLinkCode,
  requestEmailRecovery,
  loginByEmail,
  type UserProfile,
} from "../lib/api";
import { getInitData, initTelegram, isInTelegram } from "../lib/telegram";
import { useStore } from "../lib/store";
import { haptic } from "../lib/haptics";
import { legalUrl } from "../lib/legal";
import { openExternal, isNative } from "../lib/native";
import { appleSignInAvailable, signInWithApple, ВходОтменён } from "../lib/appleSignIn";
import { Button, Spinner } from "../components/ui";
import BrandMark from "../components/BrandMark";

// Дефолт — рабочий юзернейм: с неверным весь канал привлечения обрывался на
// первом клике, и это уже ловил аудит на лендинге
const BOT_USERNAME = import.meta.env.VITE_BOT_USERNAME || "simp_dating_bot";
const CODE_LENGTH = 6;

/** Понятный текст сбоя входа вместо одного «не удалось войти» на все случаи.
 *
 * Три разные ситуации, которые человек должен различать глазами:
 * сервер ответил отказом (его текст честнее нашего), сеть отвалилась
 * (ответа нет вовсе — таймаут, обрыв, недоступный хост), и всё прочее.
 * Раньше сетевой сбой и отказ сервера выглядели одинаково, и за общей
 * формулировкой пряталась, например, лежащая бэкенд-недоступность. */
function ошибкаВхода(e: unknown): string {
  const err = e as any;
  if (err?.isAxiosError) {
    const detail = err?.response?.data?.detail;
    if (typeof detail === "string" && detail) return detail;
    const безОтвета = err?.code === "ECONNABORTED" || err?.response === undefined;
    if (безОтвета) {
      return "Сервер недоступен — проверьте интернет и попробуйте ещё раз через минуту";
    }
    return "Не удалось войти. Попробуйте ещё раз.";
  }
  // Свои Error из lib/api (success:false, проверка initData) несут готовый текст
  if (e instanceof Error && e.message) return e.message;
  return "Не удалось войти. Попробуйте ещё раз.";
}

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
  const [code, setCode] = useState("");
  // WKWebView/iOS иногда восстанавливает фокус на OTP-поле и поднимает
  // клавиатуру на холодном старте. Поле остаётся readOnly, пока человек
  // сам не ткнёт — тогда снимаем блокировку.
  const [codeFieldOpen, setCodeFieldOpen] = useState(false);
  const inTelegram = isInTelegram();
  // Считываем один раз при монтировании: платформа за время жизни экрана
  // не меняется, а вызов в теле рендера означал бы, что способ входа
  // может переключиться прямо во время набора кода — стоит рантайму
  // Capacitor инициализироваться чуть позже первого рендера
  const [native] = useState(isNative);

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
    } catch (e: unknown) {
      setError(ошибкаВхода(e));
      haptic("error");
    } finally {
      setLoading(false);
    }
  }, [finishLogin]);

  const loginWithCode = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const { token, user } = await authWithLinkCode(code);
      finishLogin(token, user);
    } catch (e: unknown) {
      setError(
        (e as any)?.response?.data?.detail ??
          (ошибкаВхода(e).startsWith("Сервер недоступен")
            ? ошибкаВхода(e)
            : "Код неверный или устарел. Запросите новый командой /link у бота.")
      );
      setCode("");
      haptic("error");
    } finally {
      setLoading(false);
    }
  }, [code, finishLogin]);

  // Потерян Telegram — единственный оставшийся путь в свой аккаунт вместе с
  // оплаченной подпиской. Поэтому вход по почте есть и в мини-аппе, и в
  // нативной сборке, а не только там, где нет initData
  const [почтаОткрыта, setПочтаОткрыта] = useState(false);
  const [почта, setПочта] = useState("");
  const [почтовыйКод, setПочтовыйКод] = useState("");
  const [письмоУшло, setПисьмоУшло] = useState(false);

  const запроситьПисьмо = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      await requestEmailRecovery(почта.trim());
      // Ответ одинаковый, есть такая почта или нет: иначе по нему видно,
      // зарегистрирован ли человек в дейтинге
      setПисьмоУшло(true);
    } catch {
      setError("Не удалось отправить письмо. Попробуйте позже");
      haptic("error");
    } finally {
      setLoading(false);
    }
  }, [почта]);

  const войтиПоПочте = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const { token, user } = await loginByEmail(почта.trim(), почтовыйКод.trim());
      finishLogin(token, user);
    } catch {
      setError("Код неверный или устарел");
      haptic("error");
    } finally {
      setLoading(false);
    }
  }, [почта, почтовыйКод, finishLogin]);

  // Вход через Apple: App Store требует его там, где вход идёт через сторонний
  // сервис (Guideline 4.8). Кнопку показываем только если плагин действительно
  // собран — иначе она вела бы в никуда
  const [appleДоступен, setAppleДоступен] = useState(false);

  useEffect(() => {
    let живо = true;
    appleSignInAvailable().then((можно) => {
      if (живо) setAppleДоступен(можно);
    });
    return () => {
      живо = false;
    };
  }, []);

  const войтиЧерезApple = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const { token, user } = await signInWithApple();
      finishLogin(token, user);
    } catch (e: unknown) {
      // Отмену не показываем ошибкой: человек сам закрыл окно
      if (!(e instanceof ВходОтменён)) {
        setError(
          (e as any)?.response?.data?.detail ??
            (e instanceof Error && !(e as any).isAxiosError && e.message
              ? e.message
              : ошибкаВхода(e))
        );
        haptic("error");
      }
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
    } catch (e: unknown) {
      const err = e as any;
      setError(
        err?.response?.data?.detail ??
          (err?.response === undefined || err?.code === "ECONNABORTED"
            ? "Сервер недоступен — проверьте интернет и попробуйте позже"
            : "Гостевой вход недоступен")
      );
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

  // Холодный старт: без фейковой ошибки и без клавиатуры. WKWebView иногда
  // восстанавливает фокус на поле кода после переустановки/рестарта процесса.
  useEffect(() => {
    setError("");
    setCode("");
    setCodeFieldOpen(false);
    const blur = () => {
      const active = document.activeElement;
      if (active instanceof HTMLElement) active.blur();
    };
    blur();
    const t = window.setTimeout(blur, 120);
    return () => window.clearTimeout(t);
  }, []);

  /* ── Автовход внутри Telegram ────────────────────────────── */
  if (inTelegram && loading) {
    return (
      <div className="h-screen-safe flex flex-col items-center justify-center gap-4">
        <Logo />
        <Spinner size={22} />
        <p className="text-[14px] text-text-muted">Входим…</p>
      </div>
    );
  }

  // Композиция: бренд сверху, сразу к действию, мелочи внизу
  return (
    <div className="relative h-screen-safe overflow-hidden flex flex-col">
      <div
        aria-hidden
        className="absolute inset-0 pointer-events-none"
        style={{
          background: [
            "radial-gradient(52% 34% at 22% 8%, rgb(255 45 111 / 0.12), transparent 72%)",
            "radial-gradient(44% 30% at 78% 4%, rgb(184 22 72 / 0.10), transparent 70%)",
          ].join(","),
        }}
      />

      {/* pt-* нельзя рядом с safe-top: оба пишут padding-top, и утилита
          отступа под Dynamic Island проигрывает в каскаде. */}
      <div className="relative px-6 safe-top">
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ type: "spring", stiffness: 340, damping: 28 }}
          className="flex items-center gap-3 pt-6"
        >
          <Logo animated />
          <div className="min-w-0">
            <h1 className="text-[28px] font-bold text-text tracking-[-0.03em] leading-none">
              Симп
            </h1>
            <p className="mt-1.5 text-[14px] text-text-muted leading-none">
              знакомства
            </p>
          </div>
        </motion.div>
      </div>

      <div className="relative flex-1 min-h-0" aria-hidden />

      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.08, type: "spring", stiffness: 320, damping: 30 }}
        className="relative px-6 pb-6 safe-bottom flex flex-col gap-2.5"
      >
        {error && (
          <div
            role="alert"
            className="mb-1 px-4 py-3 rounded-[var(--radius-tile)]
                       bg-danger/10 border border-danger/35 text-danger
                       text-[13.5px] leading-snug"
          >
            {error}
          </div>
        )}

        {/* Нативное приложение: Telegram initData здесь недоступен, поэтому
            вход идёт по одноразовому коду, который выдаёт бот командой /link */}
        {native && !inTelegram ? (
          <>
            {/* Apple требует, чтобы вход через Apple не был визуально слабее
                альтернатив, поэтому он идёт первым и полноразмерной кнопкой */}
            {appleДоступен && (
              <>
                <button
                  onClick={войтиЧерезApple}
                  disabled={loading}
                  className="w-full h-[52px] rounded-[var(--radius-control)]
                             bg-white text-black text-[16px] font-semibold
                             flex items-center justify-center gap-2
                             disabled:opacity-60 active:scale-[0.99] transition-transform"
                >
                  <svg width="17" height="20" viewBox="0 0 17 20" fill="currentColor" aria-hidden="true">
                    <path d="M14.2 10.6c0-2.3 1.9-3.4 2-3.5-1.1-1.6-2.8-1.8-3.4-1.8-1.5-.1-2.8.8-3.5.8s-1.9-.8-3.1-.8C4.5 5.3 2.8 6.3 1.9 8c-1.8 3.2-.5 7.9 1.3 10.5.9 1.3 1.9 2.7 3.3 2.6 1.3 0 1.8-.8 3.4-.8s2 .8 3.4.8 2.3-1.3 3.2-2.6c1-1.5 1.4-2.9 1.4-3-.1 0-2.7-1-2.7-3.9zM11.9 3.6c.7-.9 1.2-2.1 1.1-3.3-1 0-2.3.7-3 1.6-.7.8-1.2 2-1.1 3.2 1.1.1 2.3-.6 3-1.5z"/>
                  </svg>
                  Войти через Apple
                </button>
                <p className="text-[12px] text-text-faint text-center -mt-0.5">
                  или войдите кодом из бота
                </p>
              </>
            )}

            <label
              htmlFor="link-code"
              className="text-[13px] text-text-secondary text-center"
            >
              Введите код из бота — команда <code className="text-text">/link</code>
            </label>
            <input
              id="link-code"
              value={code}
              readOnly={!codeFieldOpen}
              onPointerDown={() => {
                if (!codeFieldOpen) setCodeFieldOpen(true);
              }}
              onFocus={() => {
                if (!codeFieldOpen) {
                  setCodeFieldOpen(true);
                }
              }}
              onChange={(e) => {
                setCode(e.target.value.replace(/\D/g, "").slice(0, CODE_LENGTH));
                setError("");
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && code.length === CODE_LENGTH && !loading) {
                  loginWithCode();
                }
              }}
              inputMode="numeric"
              autoComplete="one-time-code"
              autoFocus={false}
              placeholder="000000"
              aria-label="Код входа из бота"
              className="w-full h-[56px] rounded-[var(--radius-control)]
                         bg-surface-2 border border-hairline text-center
                         text-[26px] tracking-[0.4em] font-semibold
                         text-text placeholder:text-text-faint
                         focus:outline-none focus:border-accent"
            />
            <Button
              size="lg"
              fullWidth
              onClick={loginWithCode}
              disabled={loading || code.length !== CODE_LENGTH}
            >
              {loading ? <Spinner size={20} /> : "Войти"}
            </Button>
            <Button
              variant="secondary"
              size="md"
              fullWidth
              onClick={() => openExternal(`https://t.me/${BOT_USERNAME}?start=link`)}
              disabled={loading}
            >
              Получить код в Telegram
            </Button>
          </>
        ) : (
          <>
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

            {/* Гостевой вход работает только при DEBUG на бэкенде. В проде
                запрос возвращал ошибку, и для человека это выглядело не как
                «функции нет», а как сломанная кнопка. `import.meta.env.DEV`
                вырезается из продакшн-сборки целиком, поэтому там кнопки
                просто не будет */}
            {import.meta.env.DEV && !inTelegram && (
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
          </>
        )}

        {/* Вход по почте — для тех, кто потерял Telegram. Прячем за ссылкой:
            основной путь один, а этот нужен редко и не должен спорить с ним */}
        {почтаОткрыта ? (
          <div className="flex flex-col gap-2.5 mt-1">
            <input
              type="email"
              inputMode="email"
              autoComplete="email"
              value={почта}
              onChange={(e) => setПочта(e.target.value)}
              placeholder="Почта, привязанная к аккаунту"
              disabled={письмоУшло || loading}
              aria-label="Почта для восстановления доступа"
              className="w-full h-[52px] px-4 rounded-[var(--radius-control)]
                         bg-surface-2 border border-border text-[15px]
                         text-text placeholder:text-text-faint
                         focus:outline-none focus:border-primary disabled:opacity-60"
            />
            {письмоУшло && (
              <>
                <p className="text-[12.5px] text-text-muted text-center">
                  Если такая почта привязана, код уже отправлен. Он действует 15 минут.
                </p>
                <input
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  value={почтовыйКод}
                  onChange={(e) =>
                    setПочтовыйКод(e.target.value.replace(/\D/g, "").slice(0, 6))
                  }
                  placeholder="000000"
                  aria-label="Код из письма"
                  className="w-full h-[52px] rounded-[var(--radius-control)]
                             bg-surface-2 border border-border text-center
                             text-[22px] tracking-[0.35em] font-semibold
                             text-text placeholder:text-text-faint
                             focus:outline-none focus:border-primary"
                />
              </>
            )}
            <Button
              size="md"
              fullWidth
              disabled={loading || (письмоУшло ? почтовыйКод.length < 6 : !почта.includes("@"))}
              onClick={письмоУшло ? войтиПоПочте : запроситьПисьмо}
            >
              {loading ? <Spinner size={18} /> : письмоУшло ? "Войти" : "Получить код"}
            </Button>
            <button
              onClick={() => {
                setПочтаОткрыта(false);
                setПисьмоУшло(false);
                setError("");
              }}
              className="text-[12.5px] text-text-muted underline underline-offset-2"
            >
              Назад
            </button>
          </div>
        ) : (
          <button
            onClick={() => setПочтаОткрыта(true)}
            className="mt-1 text-[12.5px] text-text-muted underline underline-offset-2 self-center"
          >
            Потеряли доступ к Telegram?
          </button>
        )}

        <p className="mt-2 text-[11.5px] text-text-faint text-center leading-relaxed">
          Сервис только для лиц старше 18 лет. Продолжая, вы принимаете{" "}
          {/* Абсолютный адрес обязателен: `target="_blank"` в нативной сборке уходит
              в системный браузер, а `/terms.html` разворачивается там от
              `capacitor://localhost` — открыть такое нечем, ссылка молча мертва.
              Мертва она именно на экране, где человека просят принять документ. */}
          <a
            href={legalUrl("terms")}
            target="_blank"
            rel="noopener noreferrer"
            className="text-text-muted underline underline-offset-2"
          >
            Условия
          </a>{" "}
          и{" "}
          <a
            href={legalUrl("privacy")}
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
      initial={animated ? { scale: 0.9, opacity: 0 } : false}
      animate={animated ? { scale: 1, opacity: 1 } : undefined}
      transition={{ type: "spring", stiffness: 300, damping: 24 }}
      className="shrink-0"
    >
      <BrandMark size={48} />
    </motion.div>
  );
}
