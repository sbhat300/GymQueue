import { apiRequest } from "./client";
import type { MachineNow, MachineStats } from "../types";

export function getMachineStats(machineId: string) {
  return apiRequest<MachineStats>(`/machines/${machineId}/stats`);
}

export function getCampusMachineStats(campusId: string) {
  return apiRequest<MachineNow[]>(`/campuses/${campusId}/machine-stats`);
}
