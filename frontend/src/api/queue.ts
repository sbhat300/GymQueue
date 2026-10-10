import { apiRequest } from "./client";
import type { QueueEntry } from "../types";

export function getQueue(machineId: string) {
  return apiRequest<QueueEntry[]>(`/machines/${machineId}/queue`);
}

export function joinQueue(machineId: string) {
  return apiRequest<QueueEntry>(`/machines/${machineId}/queue/join`, { method: "POST" });
}

export function leaveQueue(machineId: string, entryId: string) {
  return apiRequest<QueueEntry>(`/machines/${machineId}/queue/${entryId}/leave`, { method: "POST" });
}

export function checkIn(machineId: string, entryId: string) {
  return apiRequest<QueueEntry>(`/machines/${machineId}/queue/${entryId}/check-in`, { method: "POST" });
}

export function finishTurn(machineId: string, entryId: string) {
  return apiRequest<QueueEntry>(`/machines/${machineId}/queue/${entryId}/finish`, { method: "POST" });
}

export function startRest(machineId: string, entryId: string) {
  return apiRequest<QueueEntry>(`/machines/${machineId}/queue/${entryId}/rest/start`, { method: "POST" });
}

export function returnFromRest(machineId: string, entryId: string) {
  return apiRequest<QueueEntry>(`/machines/${machineId}/queue/${entryId}/rest/return`, { method: "POST" });
}

export function myQueueEntries() {
  return apiRequest<QueueEntry[]>(`/users/me/queue-entries`);
}
