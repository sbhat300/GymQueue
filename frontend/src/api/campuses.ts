import { apiRequest } from "./client";
import type { Campus } from "../types";

export function listCampuses() {
  return apiRequest<Campus[]>("/campuses");
}
