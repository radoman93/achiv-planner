import type { Metadata } from "next";
import "./globals.css";
import Providers from "@/lib/providers";

export const metadata: Metadata = {
  title: "WoW Achievement Planner",
  description:
    "Generate personalized, optimized achievement routes for World of Warcraft.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="dark">
      <body className="font-sans antialiased min-h-screen bg-background text-text-primary">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
