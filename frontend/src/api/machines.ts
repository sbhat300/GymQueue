import { apiRequest } from "./client";
import type { Machine } from "../types";

export function listMachines(campusId: string) {
  return apiRequest<Machine[]>(`/campuses/${campusId}/machines`);
}

export function getMachine(machineId: string) {
  return apiRequest<Machine>(`/machines/${machineId}`);
}
