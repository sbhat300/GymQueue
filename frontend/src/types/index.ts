export interface User {
  id: string;
  netid: string;
  display_name: string | null;
  onboarding_complete: boolean;
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
