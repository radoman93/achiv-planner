import NavShell from "@/components/nav-shell";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return <NavShell>{children}</NavShell>;
}
