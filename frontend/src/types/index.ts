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

export interface BusyHour {
  hour: number;
  people: number | null; // average people in the queue that hour today; null = no data
  samples: number;
}

/** [min, max] seconds - every turn is assumed to take 10-15 min */
export type WaitRange = [number, number];

export interface MachineNow {
  machine_id: string;
  in_use: boolean;
  queue_length: number; // entries waiting
  people_in_queue: number; // everyone on the machine + waiting, partners counted individually
  people_on_camera: number | null; // null = no live camera on this machine
  turns_ahead: number;
  estimated_wait_seconds: WaitRange;
  turn_seconds: WaitRange;
}

export interface MachineStats extends MachineNow {
  entry_wait_seconds: Record<string, WaitRange>;
  local_hour: number; // gym's timezone
  busy_today: BusyHour[];
  includes_demo_data: boolean;
}
