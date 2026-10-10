export interface User {
  id: string;
  netid: string;
  display_name: string | null;
  onboarding_complete: boolean;
  face_enrolled: boolean;
}

export interface Campus {
  id: string;
  name: string;
  slug: string;
}

export interface Machine {
  id: string;
  campus_id: string;
  name: string;
  category: string;
  is_active: boolean;
  grace_period_seconds: number;
  rest_period_seconds: number;
  max_rests: number;
}

export type QueueState = "waiting" | "grace" | "active" | "resting" | "done" | "removed";
export type GraceReason = "turn_start" | "end_of_use" | null;

export interface QueueEntryUser {
  id: string;
  display_name: string;
}

export interface QueueEntry {
  id: string;
  machine_id: string;
  state: QueueState;
  grace_reason: GraceReason;
  joined_at: string;
  active_started_at: string | null;
  grace_deadline: string | null;
  rest_started_at: string | null;
  rest_deadline: string | null;
  rest_count: number;
  users: QueueEntryUser[];
}

export interface JoinRequest {
  id: string;
  machine_id: string;
  queue_entry_id: string;
  requester_id: string;
  requester_display_name: string;
  target_id: string;
  target_display_name: string;
  status: "pending" | "accepted" | "rejected" | "cancelled" | "expired";
  created_at: string;
  resolved_at: string | null;
}

export interface WsEvent<T = Record<string, unknown>> {
  type: string;
  ts: string;
  data: T;
}

export interface BusyCell {
  hour: number;
  busy: number | null; // share of time in use, 0-1; null = no data for that hour
  queue: number | null; // average people waiting
  samples: number;
}

export interface MachineNow {
  machine_id: string;
  in_use: boolean;
  queue_length: number;
  people_on_camera: number | null; // null = no live camera on this machine
  estimated_wait_seconds: number;
  typical_session_seconds: number;
  typical_session_source: "history" | "default";
  sessions_counted: number;
}

export interface MachineStats extends MachineNow {
  entry_wait_seconds: Record<string, number>;
  local_weekday: number; // 0 = Monday, gym's timezone
  local_hour: number;
  busy_times: BusyCell[][]; // [Mon..Sun][0..23]
  history_days: number;
  includes_demo_data: boolean;
}
