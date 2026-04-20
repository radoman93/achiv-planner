"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import api, { type UserProfile, type ApiEnvelope } from "./api-client";

export function useAuth() {
  const qc = useQueryClient();

  const { data, isLoading } = useQuery<UserProfile | null>({
    queryKey: ["auth", "me"],
    queryFn: async () => {
      try {
        const res = await api.get<ApiEnvelope<UserProfile>>("/users/me");
        return res.data.data;
      } catch {
        return null;
      }
    },
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  return {
    user: data ?? null,
    isLoading,
    isAuthenticated: !!data,
    logout: async () => {
      await api.post("/auth/logout");
      qc.setQueryData(["auth", "me"], null);
    },
  };
}
