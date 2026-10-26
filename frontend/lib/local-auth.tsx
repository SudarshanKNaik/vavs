"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

export type AppRole = "doctor" | "patient" | "ngo";
// Roles served by the shared /api/auth/* endpoints; NGOs use /api/ngo/auth/*.
type DoctorPatientRole = Exclude<AppRole, "ngo">;

type AuthUser = {
  sub: string;
  name: string;
  email: string;
  picture?: string;
  username?: string;
  mobile?: string;
  role: AppRole;
  account_id?: string;
  doctor_id?: string;
  patient_id?: string;
  ngo_id?: string;
  ngo_name?: string;
  ngo_member_role?: "admin" | "staff";
};

export type AuthSession = {
  token: string;
  user: AuthUser;
};

type LoginRedirectOptions = {
  appState?: { returnTo?: string };
  authorizationParams?: { screen_hint?: "signup" | "login" };
};

type AuthContextValue = {
  isLoading: boolean;
  isAuthenticated: boolean;
  user: AuthUser | undefined;
  token: string | undefined;
  loginWithRedirect: (options?: LoginRedirectOptions) => Promise<void>;
  logout: (options?: { logoutParams?: { returnTo?: string } }) => void;
  loginWithPassword: (input: { role: DoctorPatientRole; email: string; password: string }) => Promise<AuthSession>;
  registerWithPassword: (input: {
    role: DoctorPatientRole;
    email: string;
    password: string;
    username: string;
    mobile: string;
    otp_code: string;
  }) => Promise<AuthSession>;
  sendOtpCode: (input: { role: DoctorPatientRole; email: string; purpose: "login" | "register" }) => Promise<void>;
  /** Store a session issued by another auth endpoint (the NGO portal). */
  startSession: (session: AuthSession) => void;
};

const SESSION_KEY = "caresync_local_auth_session";
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const AuthContext = createContext<AuthContextValue | null>(null);

function nextAuthRoute(options?: LoginRedirectOptions) {
  const returnTo = options?.appState?.returnTo || "";
  const isSignup = options?.authorizationParams?.screen_hint === "signup";
  const isPatient = returnTo.startsWith("/patient");

  if (returnTo.startsWith("/ngo")) {
    return isSignup ? "/ngo-signUp" : "/ngo-signIn";
  }
  if (isPatient) {
    return isSignup ? "/patient-signUp" : "/patient-signIn";
  }
  return isSignup ? "/signUp" : "/signIn";
}

export function LocalAuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(true);
  const [session, setSession] = useState<AuthSession | null>(null);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(SESSION_KEY);
      if (raw) {
        setSession(JSON.parse(raw));
      }
    } catch {
      setSession(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const persistSession = useCallback((next: AuthSession | null) => {
    setSession(next);
    if (next) {
      window.localStorage.setItem(SESSION_KEY, JSON.stringify(next));
      return;
    }
    window.localStorage.removeItem(SESSION_KEY);
  }, []);

  const sendOtpCode = useCallback(async (input: { role: DoctorPatientRole; email: string; purpose: "login" | "register" }) => {
    const response = await fetch(`${API_URL}/api/auth/otp/send`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });

    if (!response.ok) {
      const detail = await response.text().catch(() => response.statusText);
      throw new Error(detail || "Failed to send OTP");
    }
  }, []);

  const loginWithPassword = useCallback(async (input: { role: DoctorPatientRole; email: string; password: string }) => {
    const response = await fetch(`${API_URL}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });

    if (!response.ok) {
      const detail = await response.text().catch(() => response.statusText);
      throw new Error(detail || "Login failed");
    }

    const data = (await response.json()) as AuthSession;
    persistSession(data);
    return data;
  }, [persistSession]);

  const registerWithPassword = useCallback(async (input: {
    role: DoctorPatientRole;
    email: string;
    password: string;
    username: string;
    mobile: string;
    otp_code: string;
  }) => {
    const response = await fetch(`${API_URL}/api/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });

    if (!response.ok) {
      const detail = await response.text().catch(() => response.statusText);
      throw new Error(detail || "Registration failed");
    }

    const data = (await response.json()) as AuthSession;
    persistSession(data);
    return data;
  }, [persistSession]);

  const loginWithRedirect = useCallback(async (options?: LoginRedirectOptions) => {
    router.push(nextAuthRoute(options));
  }, [router]);

  const logout = useCallback((options?: { logoutParams?: { returnTo?: string } }) => {
    if (session?.user.role === "ngo" && session.token) {
      // Revoke the server-side NGO session; local sign-out proceeds regardless.
      fetch(`${API_URL}/api/ngo/auth/logout`, {
        method: "POST",
        headers: { Authorization: `Bearer ${session.token}` },
      }).catch(() => undefined);
    }
    persistSession(null);
    router.push(options?.logoutParams?.returnTo || "/");
  }, [persistSession, router, session]);

  const value = useMemo<AuthContextValue>(() => ({
    isLoading,
    isAuthenticated: !!session?.token,
    user: session?.user,
    token: session?.token,
    loginWithRedirect,
    logout,
    loginWithPassword,
    registerWithPassword,
    sendOtpCode,
    startSession: persistSession,
  }), [isLoading, session, loginWithRedirect, logout, loginWithPassword, registerWithPassword, sendOtpCode, persistSession]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useLocalAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useLocalAuth must be used within LocalAuthProvider");
  }
  return ctx;
}
