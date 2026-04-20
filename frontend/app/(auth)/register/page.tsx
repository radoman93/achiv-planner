"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import api from "@/lib/api-client";
import { useQueryClient } from "@tanstack/react-query";
import { Shield } from "lucide-react";

export default function RegisterPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const passwordStrength = (() => {
    if (!password) return { label: "", color: "" };
    if (password.length < 8) return { label: "Too short", color: "bg-error" };
    const hasUpper = /[A-Z]/.test(password);
    const hasNumber = /[0-9]/.test(password);
    const hasSpecial = /[^A-Za-z0-9]/.test(password);
    const score = [hasUpper, hasNumber, hasSpecial, password.length >= 12].filter(Boolean).length;
    if (score <= 1) return { label: "Weak", color: "bg-error" };
    if (score === 2) return { label: "Fair", color: "bg-warning" };
    if (score === 3) return { label: "Good", color: "bg-tier-high" };
    return { label: "Strong", color: "bg-success" };
  })();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!email || !password) {
      setError("All fields are required");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    setLoading(true);
    try {
      await api.post("/auth/register", { email, password });
      qc.invalidateQueries({ queryKey: ["auth", "me"] });
      router.push("/onboarding");
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } };
      setError(axiosErr.response?.data?.detail || "Registration failed");
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
      <h1 className="text-2xl font-bold text-center mb-2">Create Account</h1>
      <p className="text-text-secondary text-center text-sm mb-6">
        Start optimizing your achievement routes
      </p>

      <button
        onClick={handleBattleNet}
        className="w-full flex items-center justify-center gap-2 bg-[#148eff] hover:bg-[#0070e0] text-white font-semibold rounded py-2 transition-colors mb-2"
      >
        <Shield size={18} />
        Fastest: Connect Battle.net
      </button>
      <p className="text-xs text-text-secondary text-center mb-4">
        Automatically imports your characters and achievement data
      </p>

      <div className="relative my-6">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-border" />
        </div>
        <div className="relative flex justify-center text-sm">
          <span className="bg-surface px-2 text-text-secondary">or register with email</span>
        </div>
      </div>

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
          />
        </div>
        <div>
          <label className="block text-sm text-text-secondary mb-1">Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full bg-surface-elevated border border-border rounded px-3 py-2 text-text-primary focus:outline-none focus:border-primary"
          />
          {password && (
            <div className="flex items-center gap-2 mt-1">
              <div className="flex-1 h-1 rounded bg-border overflow-hidden">
                <div className={`h-full ${passwordStrength.color} transition-all`} style={{ width: passwordStrength.label === "Strong" ? "100%" : passwordStrength.label === "Good" ? "75%" : passwordStrength.label === "Fair" ? "50%" : "25%" }} />
              </div>
              <span className="text-xs text-text-secondary">{passwordStrength.label}</span>
            </div>
          )}
        </div>
        <div>
          <label className="block text-sm text-text-secondary mb-1">Confirm Password</label>
          <input
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            className="w-full bg-surface-elevated border border-border rounded px-3 py-2 text-text-primary focus:outline-none focus:border-primary"
          />
          {confirmPassword && password !== confirmPassword && (
            <p className="text-xs text-error mt-1">Passwords do not match</p>
          )}
        </div>
        <button
          type="submit"
          disabled={loading}
          className="w-full bg-primary hover:bg-primary-hover text-background font-semibold rounded py-2 transition-colors disabled:opacity-50"
        >
          {loading ? "Creating account..." : "Create account"}
        </button>
      </form>

      <p className="text-center text-sm text-text-secondary mt-6">
        Already have an account?{" "}
        <Link href="/login" className="text-primary hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}
