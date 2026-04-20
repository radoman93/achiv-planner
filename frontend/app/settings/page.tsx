"use client";

import { useAuth } from "@/lib/auth";
import { useRouter } from "next/navigation";

export default function SettingsPage() {
  const { user, logout } = useAuth();
  const router = useRouter();

  const handleLogout = async () => {
    await logout();
    router.push("/login");
  };

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Settings</h1>
      <div className="bg-surface rounded-lg border border-border p-6 space-y-4">
        {user && (
          <>
            <div>
              <p className="text-sm text-text-secondary">Email</p>
              <p className="font-semibold">{user.email}</p>
            </div>
            <div>
              <p className="text-sm text-text-secondary">Tier</p>
              <p className="font-semibold capitalize">{user.tier}</p>
            </div>
            <div>
              <p className="text-sm text-text-secondary">Battle.net</p>
              <p className="font-semibold">{user.battlenet_connected ? `Connected (${user.battlenet_region})` : "Not connected"}</p>
            </div>
          </>
        )}
        <hr className="border-border" />
        <button
          onClick={handleLogout}
          className="bg-error/10 text-error border border-error/30 rounded px-4 py-2 text-sm hover:bg-error/20"
        >
          Sign out
        </button>
      </div>
    </div>
  );
}
