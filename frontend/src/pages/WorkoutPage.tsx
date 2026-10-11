import { useCallback, useEffect, useState, type FormEvent } from "react";
import { addSet, deleteSet, editSet, getTodayWorkout, listExercises } from "../api/workouts";
import { ApiError } from "../api/client";
import { useNotifications } from "../context/NotificationContext";
import type { Exercise, WorkoutEntry, WsEvent } from "../types";

const LIVE_TIMEOUT_MS = 20_000; // hide the live counter if the camera goes quiet

interface LiveCount {
  machineName: string;
  exercise: string;
  reps: number;
}

function exerciseLabel(exercises: Exercise[], key: string): string {
  return exercises.find((e) => e.key === key)?.label ?? key.replace("_", " ");
}

function formatDay(day: string): string {
  // "2026-10-10" -> "Saturday, Oct 10" (parsed as a local date, not UTC midnight)
  const [y, m, d] = day.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
}

export function WorkoutPage() {
  const { addEventListener } = useNotifications();
  const [exercises, setExercises] = useState<Exercise[]>([]);
  const [day, setDay] = useState<string | null>(null);
  const [entries, setEntries] = useState<WorkoutEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState<LiveCount | null>(null);

  const [exercise, setExercise] = useState("");
  const [reps, setReps] = useState("");
  const [weight, setWeight] = useState("");
  const [saving, setSaving] = useState(false);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editReps, setEditReps] = useState("");
  const [editWeight, setEditWeight] = useState("");
  const [editSaving, setEditSaving] = useState(false);

  const refresh = useCallback(() => {
    getTodayWorkout()
      .then((res) => {
        setDay(res.day);
        setEntries(res.entries);
      })
      .catch(() => setError("Couldn't load today's workout"));
  }, []);

  useEffect(() => {
    listExercises()
      .then((list) => {
        setExercises(list);
        setExercise((current) => current || list.find((e) => !e.camera_only)?.key || "");
      })
      .catch(() => {});
    refresh();
  }, [refresh]);

  // live rep count from the machine camera; the finished set arrives as "workout_logged"
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const unsubscribe = addEventListener((event: WsEvent) => {
      if (event.type === "rep_counted") {
        const data = event.data as { machine_name?: string; exercise?: string; reps?: number };
        setLive({ machineName: data.machine_name ?? "Machine", exercise: data.exercise ?? "", reps: data.reps ?? 0 });
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => setLive(null), LIVE_TIMEOUT_MS);
      } else if (event.type === "workout_logged") {
        setLive(null);
        refresh();
      }
    });
    return () => {
      unsubscribe();
      if (timer) clearTimeout(timer);
    };
  }, [addEventListener, refresh]);

  async function handleAdd(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await addSet(exercise, Number(reps), weight ? Number(weight) : null);
      setReps("");
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't add that set");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    setError(null);
    try {
      await deleteSet(id);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't delete that set");
    }
  }

  function startEdit(set: WorkoutEntry) {
    setError(null);
    setEditingId(set.id);
    setEditReps(String(set.reps));
    setEditWeight(set.weight_lbs != null ? String(set.weight_lbs) : "");
  }

  function cancelEdit() {
    setEditingId(null);
  }

  async function handleEditSave(e: FormEvent) {
    e.preventDefault();
    if (!editingId) return;
    setError(null);
    setEditSaving(true);
    try {
      await editSet(editingId, Number(editReps), editWeight ? Number(editWeight) : null);
      setEditingId(null);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save that set");
    } finally {
      setEditSaving(false);
    }
  }

  // group sets by exercise, in the order you first did them
  const groups: { exercise: string; label: string; sets: WorkoutEntry[] }[] = [];
  for (const entry of entries ?? []) {
    let group = groups.find((g) => g.exercise === entry.exercise);
    if (!group) {
      group = { exercise: entry.exercise, label: entry.exercise_label, sets: [] };
      groups.push(group);
    }
    group.sets.push(entry);
  }
  const totalReps = (entries ?? []).reduce((sum, e) => sum + e.reps, 0);
  const cameraOnly = exercises.filter((e) => e.camera_only);

  return (
    <div className="page">
      <h1 style={{ marginBottom: 4 }}>Today's workout</h1>
      <p className="muted" style={{ marginTop: 0, marginBottom: 20 }}>
        {day ? formatDay(day) : " "}
      </p>

      {live && (
        <div className="live-reps" aria-live="polite">
          <div className="live-reps-dot" aria-hidden="true" />
          <div>
            <div className="live-reps-label">
              Counting live · {live.machineName}
              {live.machineName.toLowerCase() !== exerciseLabel(exercises, live.exercise).toLowerCase() &&
                ` · ${exerciseLabel(exercises, live.exercise)}`}
            </div>
            <div className="live-reps-count">
              {live.reps} <span>{live.reps === 1 ? "rep" : "reps"}</span>
            </div>
          </div>
        </div>
      )}

      <div className="stat-row">
        <div className="stat">
          <div className="stat-label">Exercises</div>
          <div className="stat-value">{groups.length}</div>
        </div>
        <div className="stat">
          <div className="stat-label">Sets</div>
          <div className="stat-value">{entries?.length ?? 0}</div>
        </div>
        <div className="stat">
          <div className="stat-label">Total reps</div>
          <div className="stat-value">{totalReps}</div>
        </div>
      </div>

      <form className="card workout-form" onSubmit={handleAdd}>
        <div className="card-title" style={{ marginBottom: 10 }}>
          Add a set
        </div>
        <div className="workout-form-row">
          <label className="filter">
            Exercise
            <select className="input" value={exercise} onChange={(e) => setExercise(e.target.value)} required>
              {exercises.map((ex) => (
                <option key={ex.key} value={ex.key} disabled={ex.camera_only}>
                  {ex.label}
                  {ex.camera_only ? " (counted by camera)" : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="filter">
            Reps
            <input
              className="input workout-num"
              type="number"
              min={1}
              max={500}
              value={reps}
              onChange={(e) => setReps(e.target.value)}
              required
            />
          </label>
          <label className="filter">
            Weight (lb)
            <input
              className="input workout-num"
              type="number"
              min={0}
              max={2000}
              step="any"
              placeholder="optional"
              value={weight}
              onChange={(e) => setWeight(e.target.value)}
            />
          </label>
          <button className="btn btn-primary" type="submit" disabled={saving || !exercise}>
            {saving ? "Adding…" : "Add set"}
          </button>
        </div>
        {cameraOnly.length > 0 && (
          <p className="card-subtitle" style={{ marginTop: 10, marginBottom: 0 }}>
            {cameraOnly.map((e) => e.label).join(", ")} sets are counted automatically by the camera at the machine,
            so they can't be entered by hand.
          </p>
        )}
      </form>

      {error && <div className="error-text" style={{ margin: "12px 0" }}>{error}</div>}

      {entries === null && !error && <div className="muted">Loading…</div>}
      {entries?.length === 0 && <div className="empty-state">Nothing logged yet today.</div>}

      {groups.map((group) => (
        <div key={group.exercise} className="card workout-group">
          <div className="card-row" style={{ marginBottom: 8 }}>
            <div className="card-title">{group.label}</div>
            <div className="card-subtitle">
              {group.sets.length} {group.sets.length === 1 ? "set" : "sets"} ·{" "}
              {group.sets.reduce((s, e) => s + e.reps, 0)} reps
            </div>
          </div>
          {group.sets.map((set, i) =>
            editingId === set.id ? (
              <form key={set.id} className="workout-set is-editing" onSubmit={handleEditSave}>
                <span className="workout-set-num">Set {i + 1}</span>
                <span className="workout-edit-fields">
                  <input
                    className="input workout-edit-num"
                    type="number"
                    min={1}
                    max={500}
                    value={editReps}
                    onChange={(e) => setEditReps(e.target.value)}
                    aria-label={`Reps for set ${i + 1} of ${group.label}`}
                    autoFocus
                    required
                  />
                  <span className="muted">reps ·</span>
                  <input
                    className="input workout-edit-num"
                    type="number"
                    min={0}
                    max={2000}
                    step="any"
                    placeholder="lb"
                    value={editWeight}
                    onChange={(e) => setEditWeight(e.target.value)}
                    aria-label={`Weight for set ${i + 1} of ${group.label}`}
                  />
                  <span className="muted">lb</span>
                </span>
                <button className="btn btn-sm btn-primary" type="submit" disabled={editSaving}>
                  {editSaving ? "Saving…" : "Save"}
                </button>
                <button className="btn btn-sm btn-ghost" type="button" onClick={cancelEdit} disabled={editSaving}>
                  Cancel
                </button>
              </form>
            ) : (
              <div key={set.id} className="workout-set">
                <span className="workout-set-num">Set {i + 1}</span>
                <span className="workout-set-reps">
                  {set.reps} reps{set.weight_lbs != null ? ` · ${set.weight_lbs} lb` : ""}
                </span>
                <span className={`workout-source is-${set.source}`} title={set.machine_name ?? undefined}>
                  {set.source === "camera" ? "Camera" : "Manual"}
                </span>
                <span className="workout-set-actions">
                  <button
                    className="btn btn-sm btn-ghost"
                    onClick={() => startEdit(set)}
                    aria-label={`Edit set ${i + 1} of ${group.label}`}
                  >
                    Edit
                  </button>
                  <button
                    className="btn btn-sm btn-ghost workout-delete"
                    onClick={() => handleDelete(set.id)}
                    aria-label={`Delete set ${i + 1} of ${group.label}`}
                  >
                    ×
                  </button>
                </span>
              </div>
            )
          )}
        </div>
      ))}
    </div>
  );
}
