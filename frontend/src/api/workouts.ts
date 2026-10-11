import { apiRequest } from "./client";
import type { Exercise, WorkoutEntry } from "../types";

export function listExercises() {
  return apiRequest<Exercise[]>("/workouts/exercises");
}

export function getTodayWorkout() {
  return apiRequest<{ day: string; entries: WorkoutEntry[] }>("/workouts/today");
}

export function addSet(exercise: string, reps: number, weightLbs: number | null) {
  return apiRequest<WorkoutEntry>("/workouts/today", {
    method: "POST",
    body: { exercise, reps, weight_lbs: weightLbs },
  });
}

export function deleteSet(entryId: string) {
  return apiRequest<{ deleted: string }>(`/workouts/entries/${entryId}`, { method: "DELETE" });
}
