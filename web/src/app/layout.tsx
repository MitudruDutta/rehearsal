import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Providers } from "@/components/providers";
import "./globals.css";
import "./fonts/fonts.css";

export const metadata: Metadata = {
  title: "Rehearsal: prove your AI agent works before it ships",
  description:
    "Rehearsal builds a working copy of your application with fictional data, runs your AI agent through real jobs, and verifies every outcome in the app's own database before you deploy.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="fonts" suppressHydrationWarning>
      <body className="font-sans">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
