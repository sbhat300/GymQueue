import { apiRequest } from "./client";
import type { User } from "../types";

export interface EnrollFace {
  bbox: number[];
  yaw: number;
  pitch: number;
}

export interface EnrollStatus {
  session_id: string;
  user_id: string;
  step: string | null;
  steps: string[];
  samples: Record<string, number>;
  samples_per_pose: number;
  progress: number;
  done: boolean;
  instruction: string;
  accepted?: boolean;
  message?: string;
  face?: EnrollFace | null;
}

export interface EnrollResult {
  user_id: string;
  poses: string[];
  stored: boolean;
}

export function startEnrollment() {
  return apiRequest<EnrollStatus>("/vision/enroll/start", { method: "POST" });
}

export function sendEnrollFrame(sessionId: string, imageDataUrl: string) {
  return apiRequest<EnrollStatus>(`/vision/enroll/${sessionId}/frame`, {
    method: "POST",
    body: { image: imageDataUrl },
  });
}

export function finishEnrollment(sessionId: string) {
  return apiRequest<EnrollResult>(`/vision/enroll/${sessionId}/finish`, { method: "POST" });
}

export function cancelEnrollment(sessionId: string) {
  return apiRequest<{ cancelled: boolean }>(`/vision/enroll/${sessionId}`, { method: "DELETE" });
}

export function deleteMyFace() {
  return apiRequest<User>("/users/me/face", { method: "DELETE" });
}
