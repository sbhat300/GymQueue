import { wsBaseUrl } from "../api/client";
import type { WsEvent } from "../types";

type Listener = (event: WsEvent) => void;

export class GymSocket {
  private ws: WebSocket | null = null;
  private token: string;
  private listeners = new Set<Listener>();
  private subscribedMachines = new Set<string>();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelay = 1000;
  private closedByUser = false;

  constructor(token: string) {
    this.token = token;
    this.connect();
  }

  private connect() {
    const url = `${wsBaseUrl()}/ws?token=${encodeURIComponent(this.token)}`;
    const ws = new WebSocket(url);
    this.ws = ws;

    ws.onopen = () => {
      this.reconnectDelay = 1000;
      for (const machineId of this.subscribedMachines) {
        ws.send(JSON.stringify({ type: "subscribe", machine_id: machineId }));
      }
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as WsEvent;
        for (const listener of this.listeners) listener(data);
      } catch {
        // ignore malformed payloads
      }
    };

    ws.onclose = () => {
      if (this.closedByUser) return;
      this.reconnectTimer = setTimeout(() => this.connect(), this.reconnectDelay);
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, 15000);
    };
  }

  subscribe(machineId: string) {
    this.subscribedMachines.add(machineId);
    this.send({ type: "subscribe", machine_id: machineId });
  }

  unsubscribe(machineId: string) {
    this.subscribedMachines.delete(machineId);
    this.send({ type: "unsubscribe", machine_id: machineId });
  }

  private send(payload: Record<string, unknown>) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    }
  }

  addListener(listener: Listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  close() {
    this.closedByUser = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
  }
}
