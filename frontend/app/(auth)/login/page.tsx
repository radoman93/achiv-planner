"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import api from "@/lib/api-client";
import { useQueryClient } from "@tanstack/react-query";
import { Shield } from "lucide-react";

export default function LoginPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!email || !password) {
      setError("Email and password are required");
      return;
    }
    setLoading(true);
    try {
      await api.post("/auth/login", { email, password });
      qc.invalidateQueries({ queryKey: ["auth", "me"] });
      router.push("/dashboard");
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } };
      setError(axiosErr.response?.data?.detail || "Invalid credentials");
    } finally {
      setLoading(false);
    }
  };

  const handleBattleNet = () => {
    window.location.href =
      (process.env.NEXT_PUBLIC_API_BASE_URL || "/api") + "/auth/battlenet?region=eu";
  };

  return (
    <div className="bg-surface rounded-lg border border-border p-8">
      <h1 className="text-2xl font-bold text-center mb-2">Welcome Back</h1>
      <p className="text-text-secondary text-center text-sm mb-6">
        Sign in to your achievement planner
      </p>

      {error && (
        <div className="bg-error/10 border border-error/30 text-error rounded px-4 py-2 text-sm mb-4">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm text-text-secondary mb-1">Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full bg-surface-elevated border border-border rounded px-3 py-2 text-text-primary focus:outline-none focus:border-primary"
            placeholder="you@example.com"
          />
        </div>
        <div>
          <label className="block text-sm text-text-secondary mb-1">Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full bg-surface-elevated border border-border rounded px-3 py-2 text-text-primary focus:outline-none focus:border-primary"
            placeholder="••••••••"
          />
        </div>
        <button
          type="submit"
          disabled={loading}
          className="w-full bg-primary hover:bg-primary-hover text-background font-semibold rounded py-2 transition-colors disabled:opacity-50"
        >
          {loading ? "Signing in..." : "Sign in"}
        </button>
      </form>

      <div className="relative my-6">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-border" />
        </div>
        <div className="relative flex justify-center text-sm">
          <span className="bg-surface px-2 text-text-secondary">or</span>
        </div>
      </div>

      <button
        onClick={handleBattleNet}
        className="w-full flex items-center justify-center gap-2 bg-[#148eff] hover:bg-[#0070e0] text-white font-semibold rounded py-2 transition-colors"
      >
        <Shield size={18} />
        Sign in with Battle.net
      </button>

      <p className="text-center text-sm text-text-secondary mt-6">
        Don&apos;t have an account?{" "}
        <Link href="/register" className="text-primary hover:underline">
          Register
        </Link>
      </p>
    </div>
  );
}
