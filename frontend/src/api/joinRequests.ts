import { apiRequest } from "./client";
import type { JoinRequest } from "../types";

export function createJoinRequest(machineId: string, entryId: string) {
  return apiRequest<JoinRequest>(`/machines/${machineId}/queue/${entryId}/join-requests`, { method: "POST" });
}

export function listIncomingJoinRequests() {
  return apiRequest<JoinRequest[]>(`/join-requests/incoming`);
}

export function acceptJoinRequest(requestId: string) {
  return apiRequest<JoinRequest>(`/join-requests/${requestId}/accept`, { method: "POST" });
}

export function rejectJoinRequest(requestId: string) {
  return apiRequest<JoinRequest>(`/join-requests/${requestId}/reject`, { method: "POST" });
}

export function cancelJoinRequest(requestId: string) {
  return apiRequest<JoinRequest>(`/join-requests/${requestId}/cancel`, { method: "POST" });
}
