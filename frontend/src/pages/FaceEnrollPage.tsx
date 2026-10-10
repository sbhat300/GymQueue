import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { cancelEnrollment, finishEnrollment, sendEnrollFrame, startEnrollment, type EnrollStatus } from "../api/vision";
import { ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext";

const CAPTURE_INTERVAL_MS = 300; // ~3.3 fps, matches the vision service's guidance

type Phase = "starting" | "scanning" | "finishing" | "done" | "unavailable" | "error";

export function FaceEnrollPage() {
  const navigate = useNavigate();
  const { refreshUser } = useAuth();
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const sessionIdRef = useRef<string | null>(null);
  const capturingRef = useRef(false);

  const [phase, setPhase] = useState<Phase>("starting");
  const [status, setStatus] = useState<EnrollStatus | null>(null);
  const [note, setNote] = useState("Starting camera…");
  const [errorText, setErrorText] = useState<string | null>(null);

  useEffect(() => {
    let stream: MediaStream | null = null;
    let timer: ReturnType<typeof setInterval> | null = null;
    let cancelled = false;

    async function captureAndSend() {
      const sessionId = sessionIdRef.current;
      const video = videoRef.current;
      const canvas = canvasRef.current;
      if (capturingRef.current || cancelled || !sessionId || !video || !canvas || video.readyState < 2) return;
      capturingRef.current = true;
      try {
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        const dataUrl = canvas.toDataURL("image/jpeg", 0.8);

        const result = await sendEnrollFrame(sessionId, dataUrl);
        if (cancelled) return;
        setStatus(result);
        setNote(result.message ?? result.instruction);

        if (result.done) {
          if (timer) clearInterval(timer);
          setPhase("finishing");
          try {
            await finishEnrollment(sessionId);
            await refreshUser();
            if (!cancelled) setPhase("done");
          } catch (err) {
            if (!cancelled) {
              setErrorText(err instanceof ApiError ? err.message : "Couldn't finish enrollment");
              setPhase("error");
            }
          }
        }
      } catch {
        // a dropped frame is normal (network hiccup, brief model backlog) - the next tick retries
      } finally {
        capturingRef.current = false;
      }
    }

    async function run() {
      let started: EnrollStatus;
      try {
        started = await startEnrollment();
      } catch {
        if (!cancelled) {
          setPhase("unavailable");
          setNote("Face check-in isn't set up here yet.");
        }
        return;
      }
      if (cancelled) return;
      sessionIdRef.current = started.session_id;
      setStatus(started);
      setNote(started.instruction);

      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 } });
      } catch {
        if (!cancelled) {
          setPhase("unavailable");
          setNote("Couldn't access your camera - check your browser's camera permission.");
        }
        return;
      }
      if (cancelled) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      setPhase("scanning");
      timer = setInterval(() => void captureAndSend(), CAPTURE_INTERVAL_MS);
    }

    run();

    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
      stream?.getTracks().forEach((t) => t.stop());
      if (sessionIdRef.current) cancelEnrollment(sessionIdRef.current).catch(() => {});
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const scanning = phase === "starting" || phase === "scanning" || phase === "finishing";

  return (
    <div className="auth-page" style={{ maxWidth: 480 }}>
      <h1>Scan your face</h1>
      <p className="muted">
        Required before you can join a queue: this is how machines recognise you automatically, so you don't have
        to tap "check in" or "finish" yourself.
      </p>
      <p className="card-subtitle" style={{ marginBottom: 16 }}>
        By scanning, you agree to GymQueue storing a numeric face signature (not photos) on the gym's camera server,
        used only to recognise you at machines. You can re-scan or delete it anytime from your Account page (tap
        your name at the top).
      </p>

      {scanning && (
        <div className="card">
          <div className="face-scan-frame">
            {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
            <video ref={videoRef} className="face-scan-video" muted playsInline autoPlay />
          </div>
          <canvas ref={canvasRef} style={{ display: "none" }} />
          <div className="progress-bar">
            <div className="progress-bar-fill" style={{ width: `${(status?.progress ?? 0) * 100}%` }} />
          </div>
          <div className="panel-title" style={{ marginTop: 10 }}>
            {status?.instruction ?? "Starting camera…"}
          </div>
          <p className={status?.accepted ? "muted" : "error-text"} style={{ minHeight: 18 }}>
            {phase === "finishing" ? "All poses captured - saving…" : note}
          </p>
        </div>
      )}

      {phase === "done" && (
        <div className="card">
          <div className="card-title">You're all set!</div>
          <p className="card-subtitle">Machines will recognise you automatically from now on.</p>
          <button className="btn btn-primary" style={{ marginTop: 12 }} onClick={() => navigate("/")}>
            Continue
          </button>
        </div>
      )}

      {phase === "unavailable" && (
        <div className="card">
          <p className="muted">{note}</p>
          <p className="card-subtitle">Ask a staff member to check the camera system, then try again.</p>
          <button className="btn" style={{ marginTop: 12 }} onClick={() => window.location.reload()}>
            Try again
          </button>
        </div>
      )}

      {phase === "error" && (
        <div className="card">
          <p className="error-text">{errorText}</p>
          <button className="btn" style={{ marginTop: 12 }} onClick={() => window.location.reload()}>
            Try again
          </button>
        </div>
      )}
    </div>
  );
}
