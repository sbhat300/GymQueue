import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import * as authApi from "../api/auth";
import { setAuthToken } from "../api/client";
import type { User } from "../types";

interface AuthContextValue {
  user: User | null;
  token: string | null;
  loading: boolean;
  login: (netid: string, password: string) => Promise<void>;
  signup: (netid: string, password: string) => Promise<void>;
  logout: () => void;
  setProfile: (displayName: string) => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const TOKEN_KEY = "gymqueue_token";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const stored = localStorage.getItem(TOKEN_KEY);
    if (!stored) {
      setLoading(false);
      return;
    }
    setAuthToken(stored);
    authApi
      .getMe()
      .then((me) => {
        setToken(stored);
        setUser(me);
      })
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY);
        setAuthToken(null);
      })
      .finally(() => setLoading(false));
  }, []);

  function applySession(accessToken: string, sessionUser: User) {
    localStorage.setItem(TOKEN_KEY, accessToken);
    setAuthToken(accessToken);
    setToken(accessToken);
    setUser(sessionUser);
  }

  async function login(netid: string, password: string) {
    const res = await authApi.login(netid, password);
    applySession(res.access_token, res.user);
  }

  async function signup(netid: string, password: string) {
    const res = await authApi.signup(netid, password);
    applySession(res.access_token, res.user);
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    setAuthToken(null);
    setToken(null);
    setUser(null);
  }

  async function setProfile(displayName: string) {
    const updated = await authApi.setProfile(displayName);
    setUser(updated);
  }

  return (
    <AuthContext.Provider value={{ user, token, loading, login, signup, logout, setProfile }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
