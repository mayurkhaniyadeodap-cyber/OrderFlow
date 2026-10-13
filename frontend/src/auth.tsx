import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, setUnauthorizedHandler, tokenStore } from "./api";
import type { ClientConfig, Role, User } from "./types";

interface AuthState {
  user: User | null;
  config: ClientConfig | null;
  loading: boolean;
  notice: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  clearNotice: () => void;
  refreshKey: number;
  refresh: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

interface MeResponse {
  user: User;
  config: ClientConfig;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [config, setConfig] = useState<ClientConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const loadMe = useCallback(async () => {
    const me = await api.get<MeResponse>("/api/me");
    setUser(me.user);
    setConfig(me.config);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler((message) => {
      setUser(null);
      setConfig(null);
      setNotice(message || "Your session has ended. Please sign in again.");
    });
    if (!tokenStore.get()) {
      setLoading(false);
      return;
    }
    loadMe()
      .catch(() => tokenStore.clear())
      .finally(() => setLoading(false));
  }, [loadMe]);

  const login = useCallback(
    async (username: string, password: string) => {
      const res = await api.post<{ access_token: string }>("/api/login", { username, password });
      tokenStore.set(res.access_token);
      setNotice(null);
      await loadMe();
    },
    [loadMe],
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/api/logout");
    } catch {
      /* token may already be expired; sign out locally anyway */
    }
    tokenStore.clear();
    setUser(null);
    setConfig(null);
    setNotice("You have signed out.");
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      config,
      loading,
      notice,
      login,
      logout,
      clearNotice: () => setNotice(null),
      refreshKey,
      refresh: () => setRefreshKey((k) => k + 1),
    }),
    [user, config, loading, notice, login, logout, refreshKey],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

export function useRole(): Role {
  const { user } = useAuth();
  if (!user) throw new Error("Not signed in");
  return user.role;
}
