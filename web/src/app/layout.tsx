import type { Metadata } from "next";
import { Bricolage_Grotesque, Instrument_Sans } from "next/font/google";
import type { ReactNode } from "react";
import { Providers } from "@/components/providers";
import "./globals.css";

const head = Bricolage_Grotesque({ subsets: ["latin"], weight: ["500", "700"], variable: "--font-head-next" });
const ui = Instrument_Sans({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-ui-next" });

export const metadata: Metadata = {
  title: "Rehearsal: a dress rehearsal for your AI agent",
  description:
    "Rehearsal builds a working copy of your application with fictional data, runs your AI agent through real jobs, and verifies every outcome in the app's own database before you deploy.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${head.variable} ${ui.variable}`} suppressHydrationWarning>
      <body className="font-sans">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
