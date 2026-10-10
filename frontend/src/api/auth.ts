import { apiRequest } from "./client";
import type { User } from "../types";

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export function signup(netid: string, password: string) {
  return apiRequest<TokenResponse>("/auth/signup", { method: "POST", body: { netid, password } });
}

export function login(netid: string, password: string) {
  return apiRequest<TokenResponse>("/auth/login", { method: "POST", body: { netid, password } });
}

export function getMe() {
  return apiRequest<User>("/users/me");
}

export function setProfile(display_name: string) {
  return apiRequest<User>("/users/me/profile", { method: "PATCH", body: { display_name } });
}
