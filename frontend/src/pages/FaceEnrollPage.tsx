import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { cancelEnrollment, finishEnrollment, sendEnrollFrame, startEnrollment, type EnrollStatus } from "../api/vision";
import { ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { FaceIdScanner } from "../components/FaceIdScanner";

const CAPTURE_INTERVAL_MS = 300; // ~3.3 fps, matches the vision service's guidance

type Phase = "starting" | "scanning" | "finishing" | "done" | "unavailable" | "error";

export function FaceEnrollPage() {
  const navigate = useNavigate();
  const { refreshUser } = useAuth();
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const sessionIdRef = useRef<string | null>(null);
  const capturingRef = useRef(false);
  // your neutral head pose, learned while looking straight - the ring's glow follows changes from it
  const neutralRef = useRef<{ yaw: number; pitch: number; n: number } | null>(null);
  const stepRef = useRef<string | null>("center"); // the step the frame in flight is for

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
        if (result.accepted && result.face && stepRef.current === "center") {
          const prev = neutralRef.current ?? { yaw: 0, pitch: 0, n: 0 };
          neutralRef.current = {
            yaw: (prev.yaw * prev.n + result.face.yaw) / (prev.n + 1),
            pitch: (prev.pitch * prev.n + result.face.pitch) / (prev.n + 1),
            n: prev.n + 1,
          };
        }
        stepRef.current = result.step;
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
      stepRef.current = started.step;
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
  const done = phase === "done";

  // where the head points now, relative to your neutral pose, in screen space (preview is mirrored)
  let pointer: { angle: number; strength: number } | null = null;
  const neutral = neutralRef.current;
  if (status?.face && neutral && status.step !== "center") {
    const dx = -(status.face.yaw - neutral.yaw) / 0.2; // ~20 degree turn = 1
    const dy = (status.face.pitch - neutral.pitch) / 0.1;
    pointer = { angle: (Math.atan2(dy, dx) * 180) / Math.PI, strength: Math.hypot(dx, dy) };
  }

  return (
    <div className="auth-page faceid-page">
      <h1>Set up face check-in</h1>
      <p className="muted">
        Machines recognise you automatically, so you never have to tap "check in" or "finish". Required before you
        can join a queue.
      </p>

      {(scanning || done) && (
        <>
          <FaceIdScanner
            videoRef={videoRef}
            samples={status?.samples ?? {}}
            samplesPerPose={status?.samples_per_pose ?? 3}
            step={status?.step ?? "center"}
            done={done}
            pointer={pointer}
          />
          <canvas ref={canvasRef} style={{ display: "none" }} />
          <div className="faceid-instruction" aria-live="polite">
            {done ? "Face registered" : phase === "finishing" ? "Saving…" : (status?.instruction ?? "Starting camera…")}
          </div>
          <p className={`faceid-message${status?.accepted || done ? " is-ok" : ""}`}>
            {done
              ? "Machines will recognise you automatically from now on."
              : phase === "finishing"
                ? "All directions captured"
                : note === status?.instruction
                  ? "" // don't repeat the instruction; only show feedback like "Move closer" or "Hold still"
                  : note}
          </p>
          {done && (
            <button className="btn btn-primary faceid-continue" onClick={() => navigate("/")}>
              Continue
            </button>
          )}
        </>
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

      <div className="privacy-note">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <rect x="5" y="11" width="14" height="10" rx="2" />
          <path d="M8 11V8a4 4 0 0 1 8 0v3" />
        </svg>
        <div>
          <strong>Your privacy</strong>
          <p>
            By scanning, you agree to GymQueue storing a numeric face signature, not photos, on the gym's camera
            server. It's used only to recognise you at machines. Re-scan or delete it anytime from your Account page
            (tap your name at the top).
          </p>
        </div>
      </div>
    </div>
  );
}
