"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import api, { type ApiEnvelope, type UserProfile } from "@/lib/api-client";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

export default function BattleNetCallbackPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [error, setError] = useState("");

  useEffect(() => {
    const checkAuth = async () => {
      try {
        const res = await api.get<ApiEnvelope<UserProfile>>("/users/me");
        const user = res.data.data;
        qc.setQueryData(["auth", "me"], user);

        // Check if user has characters — if not, new user → onboarding
        const charsRes = await api.get<ApiEnvelope<unknown[]>>("/characters");
        if (charsRes.data.data.length === 0) {
          router.push("/onboarding");
        } else {
          router.push("/dashboard");
        }
      } catch {
        setError("Failed to connect your Battle.net account. Please try again.");
      }
    };
    checkAuth();
  }, [router, qc]);

  if (error) {
    return (
      <div className="bg-surface rounded-lg border border-border p-8 text-center">
        <p className="text-error mb-4">{error}</p>
        <button
          onClick={() => router.push("/login")}
          className="bg-primary hover:bg-primary-hover text-background font-semibold rounded px-6 py-2"
        >
          Try again
        </button>
      </div>
    );
  }

  return (
    <div className="bg-surface rounded-lg border border-border p-8 text-center">
      <Loader2 className="animate-spin mx-auto mb-4 text-primary" size={32} />
      <p className="text-text-primary">Connecting your Battle.net account...</p>
    </div>
  );
}
