import NavShell from "@/components/nav-shell";

export default function BrowseLayout({ children }: { children: React.ReactNode }) {
  return <NavShell>{children}</NavShell>;
}
