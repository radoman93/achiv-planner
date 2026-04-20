import NavShell from "@/components/nav-shell";

export default function RoutesLayout({ children }: { children: React.ReactNode }) {
  return <NavShell>{children}</NavShell>;
}
