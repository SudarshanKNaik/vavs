"use client";

import { useCallback } from "react";
import { useLocalAuth } from "@/lib/local-auth";
import { NgoApiError } from "@/services/ngo-api";

/**
 * Token + error helper for NGO pages. A 401 from the API means the server-side
 * session expired or was revoked, so the user is signed out.
 */
export function useNgoSession() {
  const { token, user, logout } = useLocalAuth();

  const handleError = useCallback(
    (err: unknown): string => {
      if (err instanceof NgoApiError) {
        if (err.status === 401) {
          logout({ logoutParams: { returnTo: "/ngo-signIn" } });
        }
        return err.detail.message;
      }
      return err instanceof Error ? err.message : "Something went wrong";
    },
    [logout],
  );

  return { token: token ?? "", user, handleError };
}
