import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Camera, ImagePlus, ShieldCheck, Clock } from "lucide-react";
import { Sheet } from "./Sheet";
import { Button, Spinner, VerifiedBadge } from "./ui";
import { haptic } from "../lib/haptics";
import {
  finalizeSumsub,
  getVerificationStatus,
  requestSumsubToken,
  requestVerificationChallenge,
  submitVerification,
  type VerificationPose,
} from "../lib/api";

/* ── Sumsub WebSDK (провайдерский режим) ─────────────────────────
 * Съёмку, живость и анти-дипфейк делает модуль Sumsub в iframe: человек
 * только крутит головой, документы не запрашиваются. Кадры уходят напрямую
 * провайдеру, наш сервер после GREEN сверяет селфи с фото анкеты. */

interface SnsWebSdkInstance {
  launch: (selector: string) => void;
}
interface SnsWebSdkBuilder {
  withConf: (conf: { lang?: string }) => SnsWebSdkBuilder;
  withOptions: (opts: {
    addViewportTag?: boolean;
    adaptIframeHeight?: boolean;
  }) => SnsWebSdkBuilder;
  on: (event: string, handler: (payload?: unknown) => void) => SnsWebSdkBuilder;
  onMessage: (
    handler: (type: string, payload?: Record<string, unknown>) => void
  ) => SnsWebSdkBuilder;
  build: () => SnsWebSdkInstance;
}
declare global {
  interface Window {
    snsWebSdk?: {
      init: (
        accessToken: string,
        updateAccessToken: () => Promise<string>
      ) => SnsWebSdkBuilder;
    };
  }
}

const SUMSUB_SDK_URL =
  "https://static.sumsub.com/idensic/static/sns-websdk-builder.js";

let sdkScriptPromise: Promise<void> | null = null;

/** Скрипт SDK грузится один раз на сессию; повторные открытия шторки
 *  переиспользуют уже загруженный window.snsWebSdk. */
function loadSumsubSdk(): Promise<void> {
  if (window.snsWebSdk) return Promise.resolve();
  if (!sdkScriptPromise) {
    sdkScriptPromise = new Promise<void>((resolve, reject) => {
      const s = document.createElement("script");
      s.src = SUMSUB_SDK_URL;
      s.async = true;
      s.onload = () => resolve();
      s.onerror = () => {
        // Неудача не приколачивается навсегда: следующая попытка
        // перезагрузит скрипт (сеть могла просто мигнуть)
        sdkScriptPromise = null;
        reject(new Error("sumsub sdk failed to load"));
      };
      document.head.appendChild(s);
    });
  }
  return sdkScriptPromise;
}

/** Инструкции к позам — на языке человека, коды приходят с сервера. */
const POSE_LABEL: Record<VerificationPose, string> = {
  straight: "Смотрите прямо в камеру",
  left: "Поверните голову влево",
  right: "Поверните голову вправо",
  up: "Поднимите подбородок вверх",
  smile: "Улыбнитесь в камеру",
};

/** Тиков отсчёта на позу: ~2.7 с — успеть принять позу, но не заскучать. */
const PREP_TICKS = 3;
const TICK_MS = 900;

/** Суточный лимит отказов на сервере — чтобы честно показывать остаток. */
const DAILY_LIMIT = 5;

type Stage =
  | "loading" // тянем статус
  | "intro" // объяснение и приватность
  | "no-photo" // в анкете нет фото — сравнивать не с чем
  | "exhausted" // попытки на сегодня кончились
  | "camera" // съёмка поз (встроенный режим)
  | "provider" // модуль Sumsub в iframe (провайдерский режим)
  | "checking" // кадры ушли / ждём вердикт провайдера
  | "success"
  | "fail" // отказ с причиной
  | "retry-later" // сервис проверки лёг — попытка цела, можно повторить
  | "cam-error"; // камера не дана или сломана

/** Как часто и сколько опрашивать вердикт провайдера. Обычно Sumsub решает
 *  за секунды; 2 минуты — потолок на медленное авторевью. */
const FINALIZE_TICK_MS = 3000;
const FINALIZE_MAX_TICKS = 40;

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

interface VerificationSheetProps {
  open: boolean;
  onClose: () => void;
  /** Галочка получена — родитель обновляет профиль у себя. */
  onVerified: () => void;
  /** Нет фото анкеты — родитель ведёт в редактирование. */
  onAddPhoto: () => void;
}

export function VerificationSheet({
  open,
  onClose,
  onVerified,
  onAddPhoto,
}: VerificationSheetProps) {
  const [stage, setStage] = useState<Stage>("loading");
  const [provider, setProvider] = useState<"builtin" | "sumsub">("builtin");
  const [attemptsLeft, setAttemptsLeft] = useState(DAILY_LIMIT);
  const [poses, setPoses] = useState<VerificationPose[]>([]);
  const [poseIndex, setPoseIndex] = useState(0);
  const [countdown, setCountdown] = useState(0);
  const [flash, setFlash] = useState(false);
  const [failReason, setFailReason] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const framesRef = useRef<Blob[]>([]);
  // Флаг отмены для съёмочного цикла: закрытие шторки посреди отсчёта
  // должно молча остановить всё, а не досниматься в фоне
  const cancelRef = useRef(false);
  // Опрос вердикта провайдера не должен запускаться дважды: SDK шлёт
  // и onApplicantSubmitted, и onApplicantStatusChanged об одном событии
  const pollingRef = useRef(false);

  const stopCamera = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  /* ── Провайдерский вердикт: опрос finalize ──────────────────── */
  const pollFinalize = useCallback(async () => {
    if (pollingRef.current) return;
    pollingRef.current = true;
    setStage("checking");
    try {
      for (let i = 0; i < FINALIZE_MAX_TICKS; i++) {
        if (cancelRef.current) return;
        try {
          const итог = await finalizeSumsub();
          if (cancelRef.current) return;
          if (итог.verified) {
            haptic("success");
            setStage("success");
            onVerified();
            return;
          }
          // pending — провайдер ещё думает, ждём следующий тик
        } catch (e) {
          const err = e as {
            response?: {
              status?: number;
              data?: { detail?: string; attempts_left?: number };
            };
          };
          const status = err.response?.status;
          const detail = err.response?.data?.detail;
          if (status === 422) {
            haptic("error");
            setFailReason(detail || "Проверка не пройдена — попробуйте ещё раз");
            const left = err.response?.data?.attempts_left;
            if (typeof left === "number") setAttemptsLeft(left);
            setStage(typeof left === "number" && left <= 0 ? "exhausted" : "fail");
            return;
          }
          if (status === 400) {
            setStage("no-photo");
            return;
          }
          if (status === 429) {
            setAttemptsLeft(0);
            setStage("exhausted");
            return;
          }
          // 503 и сеть: вердикта нет, но попытка не сожжена — опрашиваем дальше
        }
        await sleep(FINALIZE_TICK_MS);
      }
      if (cancelRef.current) return;
      // Не дождались за отведённое время. Это не отказ: вердикт догонит
      // вебхуком, и галочка появится сама — честно говорим об этом
      haptic("warning");
      setFailReason(
        "Проверка ещё идёт. Можно закрыть окно — как только всё будет готово, галочка появится сама."
      );
      setStage("retry-later");
    } finally {
      pollingRef.current = false;
    }
  }, [onVerified]);

  /* ── Запуск модуля Sumsub ───────────────────────────────────── */
  const startProvider = useCallback(async () => {
    setBusy(true);
    try {
      // Сначала токен: серверные отказы (лимит, нет фото) должны показаться
      // до загрузки чужого скрипта, а не после
      const { token, attempts_left } = await requestSumsubToken();
      setAttemptsLeft(attempts_left);
      await loadSumsubSdk();
      if (cancelRef.current) return;
      const sdkGlobal = window.snsWebSdk;
      if (!sdkGlobal) throw new Error("sumsub sdk missing after load");
      setStage("provider");
      // Даём стадии отрисовать контейнер — SDK вставляет iframe в него
      for (let i = 0; i < 20 && !document.getElementById("sumsub-websdk"); i++) {
        await sleep(25);
      }
      if (cancelRef.current) return;
      sdkGlobal
        .init(token, async () => (await requestSumsubToken()).token)
        .withConf({ lang: "ru" })
        .withOptions({ addViewportTag: false, adaptIframeHeight: true })
        .onMessage((type, payload) => {
          const p = payload as { reviewStatus?: string } | undefined;
          // Съёмка закончена, заявка ушла в ревью — дальше наш опрос вердикта
          if (
            type === "idCheck.onApplicantSubmitted" ||
            (type === "idCheck.onApplicantStatusChanged" &&
              (p?.reviewStatus === "pending" || p?.reviewStatus === "completed"))
          ) {
            void pollFinalize();
          }
        })
        .on("idCheck.onError", () => haptic("warning"))
        .build()
        .launch("#sumsub-websdk");
    } catch (e) {
      const err = e as {
        response?: { status?: number; data?: { detail?: string } };
      };
      const status = err.response?.status;
      if (status === 429) {
        setAttemptsLeft(0);
        setStage("exhausted");
      } else if (status === 400) {
        setStage("no-photo");
      } else if (status === 409) {
        // Уже подтверждён (например, с другого устройства)
        setStage("success");
        onVerified();
      } else if (status) {
        setFailReason(
          err.response?.data?.detail || "Проверка сейчас недоступна — попробуйте через пару минут"
        );
        setStage("fail");
      } else {
        // Скрипт SDK не загрузился или сеть упала до старта
        setFailReason("Не получилось загрузить модуль проверки — проверьте связь");
        setStage("fail");
      }
    } finally {
      setBusy(false);
    }
  }, [onVerified, pollFinalize]);

  /* ── Статус при открытии ────────────────────────────────────── */
  useEffect(() => {
    if (!open) {
      // Уборка на закрытии: камера гаснет, цикл съёмки останавливается,
      // кадры прошлой попытки не переживают шторку
      cancelRef.current = true;
      stopCamera();
      framesRef.current = [];
      setStage("loading");
      setNotice("");
      return;
    }
    cancelRef.current = false;
    let alive = true;
    (async () => {
      try {
        const s = await getVerificationStatus();
        if (!alive) return;
        setProvider(s.provider ?? "builtin");
        setAttemptsLeft(s.attempts_left);
        if (s.is_verified) setStage("success");
        else if (!s.has_photo) setStage("no-photo");
        else if (s.attempts_left <= 0) setStage("exhausted");
        else if (s.provider === "sumsub" && s.provider_pending) {
          // Провайдерская попытка уже начата (вердикт мог прийти, пока
          // приложение было закрыто) — сразу спрашиваем итог, не заставляя
          // человека проходить съёмку заново
          setStage("checking");
          void pollFinalize();
        } else setStage("intro");
      } catch {
        if (!alive) return;
        setFailReason("Не получилось загрузить статус — проверьте связь");
        setStage("fail");
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, stopCamera]);

  useEffect(() => () => stopCamera(), [stopCamera]);

  /* ── Кадр из видео ──────────────────────────────────────────── */
  const captureFrame = useCallback((): Promise<Blob | null> => {
    return new Promise((resolve) => {
      const video = videoRef.current;
      if (!video || video.videoWidth === 0) return resolve(null);
      // 720 по длинной стороне: лицу хватает, а полотно с фронталки
      // в несколько мегапикселей гонять по сети незачем
      const MAX = 720;
      const scale = Math.min(1, MAX / Math.max(video.videoWidth, video.videoHeight));
      const w = Math.round(video.videoWidth * scale);
      const h = Math.round(video.videoHeight * scale);
      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d");
      if (!ctx) return resolve(null);
      // Зеркалим, как в превью: человек выполнял «влево/вправо», глядя в
      // «зеркало», и уйти должно то, что он видел. Промпт проверки к
      // зеркальности фронталки терпим.
      ctx.translate(w, 0);
      ctx.scale(-1, 1);
      ctx.drawImage(video, 0, 0, w, h);
      canvas.toBlob((b) => resolve(b), "image/jpeg", 0.85);
    });
  }, []);

  /* ── Отправка кадров ────────────────────────────────────────── */
  const submitFrames = useCallback(async () => {
    setStage("checking");
    setBusy(true);
    try {
      await submitVerification(framesRef.current);
      framesRef.current = [];
      haptic("success");
      setStage("success");
      onVerified();
    } catch (e) {
      const err = e as {
        response?: { status?: number; data?: { detail?: string; attempts_left?: number } };
      };
      const status = err.response?.status;
      const detail = err.response?.data?.detail;
      if (status === 422) {
        // Отказ по существу: причина человеку, остаток попыток — из ответа
        framesRef.current = [];
        haptic("error");
        setFailReason(detail || "Проверка не пройдена — попробуйте ещё раз");
        const left = err.response?.data?.attempts_left;
        if (typeof left === "number") setAttemptsLeft(left);
        setStage(typeof left === "number" && left <= 0 ? "exhausted" : "fail");
      } else if (status === 410) {
        // Задание истекло — молча берём новое и переснимаем
        framesRef.current = [];
        setNotice("Задание истекло — позы обновились");
        void startShoot();
      } else if (status === 429) {
        framesRef.current = [];
        setAttemptsLeft(0);
        setStage("exhausted");
      } else {
        // 503 и сеть: попытка не сожжена, кадры целы — дать дослать их же
        haptic("warning");
        setFailReason(detail || "Проверка сейчас недоступна — попробуйте через пару минут");
        setStage("retry-later");
      }
    } finally {
      setBusy(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onVerified]);

  /* ── Съёмочный цикл ─────────────────────────────────────────── */
  const runCapture = useCallback(
    async (список: VerificationPose[]) => {
      framesRef.current = [];
      for (let i = 0; i < список.length; i++) {
        if (cancelRef.current) return;
        setPoseIndex(i);
        for (let c = PREP_TICKS; c >= 1; c--) {
          setCountdown(c);
          haptic("select");
          await sleep(TICK_MS);
          if (cancelRef.current) return;
        }
        setCountdown(0);
        const blob = await captureFrame();
        if (cancelRef.current) return;
        if (!blob) {
          stopCamera();
          setStage("cam-error");
          return;
        }
        framesRef.current.push(blob);
        haptic("medium");
        setFlash(true);
        setTimeout(() => setFlash(false), 180);
        await sleep(320);
      }
      if (cancelRef.current) return;
      // Камера дальше не нужна — гасим до вердикта, индикатор записи
      // не должен гореть, пока человек ждёт ответа
      stopCamera();
      await submitFrames();
    },
    [captureFrame, stopCamera, submitFrames]
  );

  const startShoot = useCallback(async () => {
    setBusy(true);
    try {
      const задание = await requestVerificationChallenge();
      setAttemptsLeft(задание.attempts_left);
      setPoses(задание.poses);
      setPoseIndex(0);
      setCountdown(0);
      setStage("camera");
      // Даём стадии отрисовать <video>: getUserMedia без элемента некуда цеплять
      for (let i = 0; i < 20 && !videoRef.current; i++) await sleep(25);
      const video = videoRef.current;
      if (!video) throw new Error("video not mounted");
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 960 }, height: { ideal: 960 } },
        audio: false,
      });
      if (cancelRef.current) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      streamRef.current = stream;
      video.srcObject = stream;
      await video.play();
      // Пауза после появления картинки: человек должен увидеть себя,
      // прежде чем пойдёт отсчёт первой позы
      await sleep(700);
      if (cancelRef.current) return;
      void runCapture(задание.poses);
    } catch (e) {
      stopCamera();
      const err = e as { response?: { status?: number; data?: { detail?: string } }; name?: string };
      const status = err.response?.status;
      if (status === 429) {
        setAttemptsLeft(0);
        setStage("exhausted");
      } else if (status === 400) {
        setStage("no-photo");
      } else if (status === 409) {
        // Уже подтверждён (например, с другого устройства)
        setStage("success");
        onVerified();
      } else if (status) {
        setFailReason(err.response?.data?.detail || "Не получилось начать проверку");
        setStage("fail");
      } else {
        // Не HTTP: камера не дана / занята / нет её
        setStage("cam-error");
      }
    } finally {
      setBusy(false);
    }
  }, [onVerified, runCapture, stopCamera]);

  const текущаяПоза = poses[poseIndex];

  return (
    <Sheet open={open} onClose={onClose} title="Проверка профиля">
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={stage}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.18 }}
        >
          {stage === "loading" && (
            <div className="py-14 flex justify-center">
              <Spinner size={26} />
            </div>
          )}

          {stage === "intro" && (
            <div className="pb-2">
              <div className="flex justify-center mb-4">
                <div className="w-16 h-16 rounded-full glass-strong grid place-items-center">
                  <VerifiedBadge size={34} />
                </div>
              </div>
              <p className="text-[15px] leading-relaxed text-center mb-4">
                {provider === "sumsub"
                  ? "Галочка показывает другим, что анкета принадлежит реальному человеку. Проверку проводит независимый сервис Sumsub: короткое селфи — покрутите головой перед камерой, и всё. Никаких документов."
                  : "Галочка показывает другим, что анкета принадлежит реальному человеку. Снимите три коротких кадра с фронтальной камеры — займёт полминуты. Снимайте без фильтров и масок: проверка отклоняет изменённые лица."}
              </p>
              <div className="rounded-[var(--radius-tile)] bg-surface-2 border border-hairline p-3.5 mb-4 flex items-start gap-2.5">
                <ShieldCheck size={17} className="text-success shrink-0 mt-0.5" />
                <p className="text-[13px] leading-snug text-text-muted">
                  {provider === "sumsub"
                    ? "Запись обрабатывает Sumsub и не передаёт нам: мы получаем только итог проверки и не храним кадры. Остаётся результат — галочка."
                    : "Кадры проверяются автоматикой и сразу удаляются: мы не сохраняем их и никому не показываем. Остаётся только результат — галочка."}
                </p>
              </div>
              {attemptsLeft < DAILY_LIMIT && (
                <p className="text-caption text-text-muted text-center mb-3">
                  Осталось попыток сегодня: {attemptsLeft}
                </p>
              )}
              <Button
                fullWidth
                size="lg"
                loading={busy}
                onClick={() =>
                  void (provider === "sumsub" ? startProvider() : startShoot())
                }
              >
                <Camera size={18} />
                Начать проверку
              </Button>
            </div>
          )}

          {stage === "no-photo" && (
            <div className="pb-2 text-center">
              <div className="flex justify-center mb-4">
                <div className="w-16 h-16 rounded-full glass-strong grid place-items-center">
                  <ImagePlus size={28} className="text-text-muted" />
                </div>
              </div>
              <p className="text-[15px] leading-relaxed mb-5">
                Сначала добавьте фото в анкету — при проверке мы сравниваем
                лицо с ним.
              </p>
              <Button fullWidth size="lg" onClick={onAddPhoto}>
                Добавить фото
              </Button>
            </div>
          )}

          {stage === "exhausted" && (
            <div className="pb-2 text-center">
              <div className="flex justify-center mb-4">
                <div className="w-16 h-16 rounded-full glass-strong grid place-items-center">
                  <Clock size={28} className="text-warn" />
                </div>
              </div>
              <p className="text-[15px] leading-relaxed mb-5">
                Попытки на сегодня закончились. Возвращайтесь к проверке
                завтра — лимит обновится.
              </p>
              <Button fullWidth size="lg" variant="secondary" onClick={onClose}>
                Понятно
              </Button>
            </div>
          )}

          {stage === "camera" && (
            <div className="pb-2">
              {notice && (
                <p className="text-caption text-warn text-center mb-2">{notice}</p>
              )}
              <div className="relative mx-auto w-[240px] h-[240px] rounded-full overflow-hidden bg-surface-2 mb-4">
                <video
                  ref={videoRef}
                  autoPlay
                  playsInline
                  muted
                  className="w-full h-full object-cover -scale-x-100"
                />
                {/* Вспышка на момент снимка — понятно, что кадр взят */}
                <AnimatePresence>
                  {flash && (
                    <motion.div
                      className="absolute inset-0 bg-white"
                      initial={{ opacity: 0.85 }}
                      animate={{ opacity: 0 }}
                      exit={{ opacity: 0 }}
                      transition={{ duration: 0.18 }}
                    />
                  )}
                </AnimatePresence>
                {countdown > 0 && (
                  <div className="absolute inset-0 grid place-items-center pointer-events-none">
                    <span
                      key={countdown}
                      className="text-[56px] font-black text-white drop-shadow-[0_2px_10px_rgba(0,0,0,.6)]"
                    >
                      {countdown}
                    </span>
                  </div>
                )}
              </div>
              <p className="text-[17px] font-bold text-center mb-2 min-h-[24px]">
                {текущаяПоза ? POSE_LABEL[текущаяПоза] : ""}
              </p>
              {/* Точки прогресса по позам */}
              <div className="flex justify-center gap-1.5">
                {poses.map((_, i) => (
                  <span
                    key={i}
                    className={`w-2 h-2 rounded-full transition-colors ${
                      i < poseIndex
                        ? "bg-success"
                        : i === poseIndex
                          ? "bg-accent"
                          : "bg-surface-3"
                    }`}
                  />
                ))}
              </div>
            </div>
          )}

          {stage === "provider" && (
            <div className="pb-2">
              {/* Sumsub вставляет сюда свой iframe со съёмкой живости */}
              <div
                id="sumsub-websdk"
                className="min-h-[420px] rounded-[var(--radius-tile)] overflow-hidden bg-surface-2"
              />
              <p className="text-caption text-text-muted text-center mt-2.5">
                Съёмка идёт в защищённом модуле Sumsub. Только селфи —
                документы не нужны.
              </p>
            </div>
          )}

          {stage === "checking" && (
            <div className="py-10 text-center">
              <div className="flex justify-center mb-4">
                <Spinner size={28} />
              </div>
              <p className="text-[15px] text-text-muted">
                {provider === "sumsub"
                  ? "Sumsub проверяет запись… обычно это занимает меньше минуты"
                  : "Проверяем кадры… обычно это займёт до минуты"}
              </p>
            </div>
          )}

          {stage === "success" && (
            <div className="pb-2 text-center">
              <motion.div
                className="flex justify-center mb-4"
                initial={{ scale: 0.4, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ type: "spring", stiffness: 320, damping: 18 }}
              >
                <VerifiedBadge size={64} />
              </motion.div>
              <h3 className="text-[19px] font-extrabold mb-1.5">
                Профиль подтверждён
              </h3>
              <p className="text-[14px] text-text-muted mb-5">
                Галочка уже видна рядом с вашим именем в анкете и в деке.
              </p>
              <Button fullWidth size="lg" onClick={onClose}>
                Отлично
              </Button>
            </div>
          )}

          {stage === "fail" && (
            <div className="pb-2 text-center">
              <p className="text-[15px] leading-relaxed mb-2">{failReason}</p>
              {attemptsLeft > 0 && attemptsLeft < DAILY_LIMIT && (
                <p className="text-caption text-text-muted mb-4">
                  Осталось попыток сегодня: {attemptsLeft}
                </p>
              )}
              <Button
                fullWidth
                size="lg"
                loading={busy}
                onClick={() =>
                  void (provider === "sumsub" ? startProvider() : startShoot())
                }
                className="mb-2.5"
              >
                Попробовать ещё раз
              </Button>
              <Button fullWidth variant="ghost" onClick={onClose}>
                Позже
              </Button>
            </div>
          )}

          {stage === "retry-later" && (
            <div className="pb-2 text-center">
              <p className="text-[15px] leading-relaxed mb-4">{failReason}</p>
              {/* Встроенный режим: кадры уже сняты и попытка не сожжена —
                  дошлём их же, пересъёмка была бы наказанием за чужой сбой.
                  Провайдерский: съёмка уже у Sumsub — просто ещё раз
                  спрашиваем вердикт */}
              <Button
                fullWidth
                size="lg"
                loading={busy}
                onClick={() =>
                  void (provider === "sumsub" ? pollFinalize() : submitFrames())
                }
                className="mb-2.5"
              >
                {provider === "sumsub" ? "Проверить ещё раз" : "Отправить ещё раз"}
              </Button>
              <Button fullWidth variant="ghost" onClick={onClose}>
                Позже
              </Button>
            </div>
          )}

          {stage === "cam-error" && (
            <div className="pb-2 text-center">
              <div className="flex justify-center mb-4">
                <div className="w-16 h-16 rounded-full glass-strong grid place-items-center">
                  <Camera size={28} className="text-danger" />
                </div>
              </div>
              <p className="text-[15px] leading-relaxed mb-2">
                Не получилось включить камеру.
              </p>
              <p className="text-[13px] text-text-muted leading-snug mb-5">
                Разрешите доступ к камере в настройках устройства и попробуйте
                снова. На iPhone: Настройки → Simp → Камера.
              </p>
              <Button fullWidth size="lg" onClick={() => void startShoot()}>
                Попробовать снова
              </Button>
            </div>
          )}
        </motion.div>
      </AnimatePresence>
    </Sheet>
  );
}
