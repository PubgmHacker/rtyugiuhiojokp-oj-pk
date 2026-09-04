/**
 * Голосовая рулетка: случайный звонок одним тапом.
 *
 * Звук идёт напрямую между браузерами через WebRTC — сервер только знакомит
 * собеседников и передаёт сигналы. Микрофон запрашиваем в момент нажатия, а не
 * при открытии экрана: системный запрос без явного действия пугает и его чаще
 * отклоняют.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { Flag, Mic, MicOff, PhoneOff, SkipForward } from "lucide-react";
import { getIceServers, reportUser } from "../lib/api";
import { haptic } from "../lib/haptics";
import { useSectionOpen } from "../lib/useSectionOpen";
import { ScreenHeader } from "../components/ui";

const WS_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

type Stage = "idle" | "waiting" | "talking";

export default function VoiceRoulette() {
  useSectionOpen("voice");
  const [stage, setStage] = useState<Stage>("idle");
  const [muted, setMuted] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  // Кто на другом конце — иначе пожаловаться не на кого, а голос незнакомца
  // без кнопки жалобы это то, чего в дейтинге быть не должно
  const [partnerId, setPartnerId] = useState<string | null>(null);
  const [reported, setReported] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const localRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const iceRef = useRef<RTCIceServer[] | null>(null);
  const connectionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Экран открыт и звонок можно продолжать заводить. Одного mounted-флага
  // недостаточно: start() ждёт getIceServers()/getUserMedia(), и если за это
  // время компонент размонтируют, единственный шанс отпустить уже пойманный
  // микрофон — проверить этот флаг сразу после await, до того как поток и
  // сокет попадут в рефы.
  const activeRef = useRef(true);
  const startingRef = useRef(false);
  const startAttemptRef = useRef(0);

  const clearConnectionTimer = useCallback(() => {
    if (connectionTimerRef.current !== null) {
      clearTimeout(connectionTimerRef.current);
      connectionTimerRef.current = null;
    }
  }, []);

  /** Снести WebRTC-соединение, но оставить сокет для следующего поиска. */
  const teardownCall = useCallback(() => {
    clearConnectionTimer();
    pcRef.current?.close();
    pcRef.current = null;
    if (audioRef.current) audioRef.current.srcObject = null;
  }, [clearConnectionTimer]);

  const releaseLocalMedia = useCallback(() => {
    localRef.current?.getTracks().forEach((track) => track.stop());
    localRef.current = null;
  }, []);

  /** Полностью завершить текущий звонок, не отключая экран. */
  const stopCall = useCallback(() => {
    // Отменяем незавершённый getIceServers/getUserMedia. Иначе быстрый тап
    // «завершить» во время системного запроса позже всё равно откроет сокет.
    startAttemptRef.current += 1;
    startingRef.current = false;
    teardownCall();
    releaseLocalMedia();
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws && ws.readyState !== WebSocket.CLOSED) ws.close();
    setPartnerId(null);
    setReported(false);
    setMuted(false);
    setStage("idle");
  }, [releaseLocalMedia, teardownCall]);

  const stopAll = useCallback(() => {
    activeRef.current = false;
    stopCall();
  }, [stopCall]);

  // Уходя с экрана, обязательно отпускаем микрофон: иначе индикатор записи
  // остаётся гореть, и это выглядит как слежка
  useEffect(() => {
    activeRef.current = true;
    return stopAll;
  }, [stopAll]);

  const createPeer = useCallback(
    (sendSignal: (payload: unknown) => void) => {
      // Повторный matched не должен оставлять старый RTCPeerConnection жить
      // рядом с новым: оба могли бы одновременно захватить аудио.
      pcRef.current?.close();
      pcRef.current = null;
      const pc = new RTCPeerConnection({ iceServers: iceRef.current ?? [] });

      localRef.current?.getTracks().forEach((track) => {
        pc.addTrack(track, localRef.current as MediaStream);
      });

      pc.onicecandidate = (e) => {
        if (e.candidate) sendSignal({ candidate: e.candidate });
      };

      pc.ontrack = (e) => {
        if (audioRef.current) {
          audioRef.current.srcObject = e.streams[0];
          audioRef.current.play().catch(() => {
            /* автозапуск может быть запрещён до жеста — звук пойдёт позже */
          });
        }
      };

      pc.onconnectionstatechange = () => {
        if (pc.connectionState === "connected") {
          clearConnectionTimer();
          setStage("talking");
        }
        if (pc.connectionState === "failed") {
          setError("Не удалось соединиться. Попробуйте ещё раз.");
          stopCall();
        }
      };

      pcRef.current = pc;
      connectionTimerRef.current = setTimeout(() => {
        if (pcRef.current !== pc || pc.connectionState === "connected") return;
        setError("Соединение не установилось. Попробуйте ещё раз.");
        stopCall();
      }, 20_000);
      return pc;
    },
    [clearConnectionTimer, stopCall]
  );

  const start = useCallback(async () => {
    if (!activeRef.current || startingRef.current) return;
    startingRef.current = true;
    const attempt = ++startAttemptRef.current;
    setError("");
    setNotice("");
    setStage("waiting");
    haptic("light");

    let stream: MediaStream | null = null;
    try {
      if (!iceRef.current) iceRef.current = await getIceServers();
      if (!activeRef.current || attempt !== startAttemptRef.current) return;

      if (!localRef.current) {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      }
    } catch {
      if (!activeRef.current || attempt !== startAttemptRef.current) return;
      setError("Нужен доступ к микрофону — разрешите его в настройках браузера");
      setStage("idle");
      startingRef.current = false;
      return;
    }

    // Экран могли покинуть, пока ждали разрешение микрофона или ICE-сервера:
    // cleanup-эффект уже отработал и второй раз не сработает, так что
    // отпустить только что пойманный микрофон и не открывать сокет нужно
    // здесь, а не полагаться на размонтирование.
    if (!activeRef.current || attempt !== startAttemptRef.current) {
      stream?.getTracks().forEach((t) => t.stop());
      return;
    }
    if (stream) localRef.current = stream;

    startingRef.current = false;

    const token = localStorage.getItem("sd_token") ?? "";
    const url = `${WS_URL.replace(/^http/, "ws")}/api/voice/ws/roulette?token=${token}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    const sendSignal = (payload: unknown) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "signal", payload }));
      }
    };

    ws.onopen = () => {
      if (activeRef.current && wsRef.current === ws) {
        ws.send(JSON.stringify({ type: "find" }));
      }
    };

    ws.onmessage = async (event) => {
      if (!activeRef.current || wsRef.current !== ws) return;
      try {
        const data = JSON.parse(event.data);

        if (data.type === "matched") {
          setPartnerId(data.partner_id ?? null);
          setReported(false);
          const pc = createPeer(sendSignal);
          // Offer шлёт только тот, кого сервер назначил инициатором: иначе оба
          // отправят offer и соединение не соберётся
          if (data.initiator) {
            const offer = await pc.createOffer();
            if (!activeRef.current || pcRef.current !== pc) return;
            await pc.setLocalDescription(offer);
            sendSignal({ sdp: offer });
          }
          return;
        }

        if (data.type === "signal") {
          const pc = pcRef.current ?? createPeer(sendSignal);
          const { sdp, candidate } = data.payload ?? {};

          if (sdp) {
            await pc.setRemoteDescription(new RTCSessionDescription(sdp));
            if (sdp.type === "offer") {
              const answer = await pc.createAnswer();
              if (!activeRef.current || pcRef.current !== pc) return;
              await pc.setLocalDescription(answer);
              sendSignal({ sdp: answer });
            }
          } else if (candidate) {
            try {
              await pc.addIceCandidate(new RTCIceCandidate(candidate));
            } catch {
              /* кандидат мог прийти до описания — WebRTC переживает */
            }
          }
          return;
        }

        if (data.type === "partner_left") {
          haptic("warning");
          stopCall();
          setError("Собеседник отключился");
        }
      } catch {
        if (!activeRef.current) return;
        setError("Не удалось установить голосовое соединение");
        stopCall();
      }
    };

    ws.onerror = () => {
      if (activeRef.current && wsRef.current === ws) setError("Нет связи с сервером");
    };
    ws.onclose = () => {
      if (wsRef.current !== ws) return;
      teardownCall();
      releaseLocalMedia();
      wsRef.current = null;
      setPartnerId(null);
      setReported(false);
      if (activeRef.current) setStage("idle");
    };
  }, [createPeer, releaseLocalMedia, stopCall, teardownCall]);

  const report = useCallback(async () => {
    if (!partnerId || reported) return;
    haptic("warning");
    try {
      await reportUser(partnerId, "harassment", "Жалоба из голосовой рулетки");
      setReported(true);
      // Разрываем звонок: продолжать разговор с тем, на кого пожаловался,
      // человек почти наверняка не хочет
      stopCall();
      setNotice("Жалоба отправлена — модератор разберётся");
    } catch {
      haptic("error");
      setError("Не удалось отправить жалобу");
    }
  }, [partnerId, reported, stopCall]);

  const next = useCallback(() => {
    haptic("light");
    setError("");
    setNotice("");
    teardownCall();
    setPartnerId(null);
    setReported(false);
    const ws = wsRef.current;
    if (localRef.current && ws?.readyState === WebSocket.OPEN) {
      setStage("waiting");
      ws.send(JSON.stringify({ type: "find" }));
    } else {
      stopCall();
      void start();
    }
  }, [start, stopCall, teardownCall]);

  const безДвижения = useReducedMotion();

  const toggleMute = useCallback(() => {
    const track = localRef.current?.getAudioTracks()[0];
    if (!track) return;
    track.enabled = !track.enabled;
    setMuted(!track.enabled);
    haptic("light");
  }, []);

  return (
    <div className="flex flex-col h-[calc(100dvh-68px)]">
      <ScreenHeader title="Голосовая рулетка" />

      <div className="flex-1 flex flex-col items-center justify-center px-8 text-center">
        <audio ref={audioRef} autoPlay playsInline className="hidden" />

        {/* Диск и радар вокруг него. Пока ищем — круги расходятся от кнопки:
            ожидание видно и без надписи, а сам диск при этом стоит на месте
            (раньше он раздувался целиком и уезжал под текст). */}
        <div className="relative grid place-items-center">
          {stage === "waiting" &&
            !безДвижения &&
            [0, 0.6, 1.2].map((задержка) => (
              <motion.span
                key={задержка}
                aria-hidden="true"
                className="absolute w-32 h-32 rounded-full border border-accent/45"
                initial={{ scale: 1, opacity: 0.55 }}
                animate={{ scale: 2.1, opacity: 0 }}
                transition={{
                  duration: 1.8,
                  delay: задержка,
                  repeat: Infinity,
                  ease: "easeOut",
                }}
              />
            ))}
          <motion.button
            onClick={stage === "idle" ? start : undefined}
            disabled={stage !== "idle"}
            whileTap={stage === "idle" ? { scale: 0.95 } : undefined}
            transition={{ type: "spring", stiffness: 520, damping: 30 }}
            className={`voice-disc relative w-32 h-32 rounded-full flex items-center justify-center
                        ${stage === "idle" ? "" : "opacity-70"}`}
            aria-label={stage === "idle" ? "Начать звонок" : "Идёт поиск"}
          >
            <Mic size={44} className="text-on-accent" />
          </motion.button>
        </div>

        <p className="mt-6 text-[15px] text-text-secondary max-w-[280px]">
          {stage === "idle" && "Нажмите, чтобы начать случайный голосовой звонок"}
          {stage === "waiting" && "Ищем собеседника…"}
          {stage === "talking" && "Разговор идёт"}
        </p>

        {error && (
          <p role="alert" className="mt-4 text-[13.5px] text-danger max-w-[280px]">
            {error}
          </p>
        )}
        {notice && (
          <p role="status" aria-live="polite" className="mt-4 text-[13.5px] text-success max-w-[280px]">
            {notice}
          </p>
        )}

        {stage !== "idle" && (
          <div className="flex items-center gap-3 mt-8">
            <button
              onClick={toggleMute}
              aria-label={muted ? "Включить микрофон" : "Выключить микрофон"}
              className="w-14 h-14 rounded-full glass-strong flex items-center
                         justify-center active:scale-95 transition-transform"
            >
              {muted ? <MicOff size={20} /> : <Mic size={20} />}
            </button>

            <button
              onClick={next}
              aria-label="Следующий собеседник"
              className="w-14 h-14 rounded-full glass-strong flex items-center
                         justify-center active:scale-95 transition-transform"
            >
              <SkipForward size={20} />
            </button>

            {/* Жалоба на голос: без неё разговор с незнакомцем — единственное
                место в приложении, откуда нельзя сообщить о нарушении */}
            {partnerId && (
              <button
                onClick={report}
                disabled={reported}
                aria-label={reported ? "Жалоба отправлена" : "Пожаловаться"}
                className="w-14 h-14 rounded-full glass-strong flex items-center
                           justify-center text-warn disabled:opacity-40
                           active:scale-95 transition-transform"
              >
                <Flag size={19} />
              </button>
            )}

            <button
              onClick={stopCall}
              aria-label="Завершить"
              className="w-14 h-14 rounded-full bg-danger text-white flex items-center
                         justify-center active:scale-95 transition-transform"
            >
              <PhoneOff size={20} />
            </button>
          </div>
        )}

        <p className="mt-8 text-[12px] text-text-faint max-w-[280px] leading-snug">
          Звонок идёт напрямую между устройствами. Мы не записываем разговоры —
          но фиксируем, кто с кем говорил, чтобы разбирать жалобы.
        </p>
      </div>
    </div>
  );
}
