import type { Metadata, Viewport } from "next";
import { Geist_Mono } from "next/font/google";
import { Providers } from "@/components/providers";
import { site } from "@/lib/site";
import "./fonts/fonts.css";
import "./globals.css";

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  metadataBase: new URL(site.url),
  title: { default: "Rehearsal documentation", template: "%s | Rehearsal docs" },
  description:
    "How to build a practice world from your application, test an AI agent in it, read why an episode failed, and run the server yourself.",
  openGraph: { siteName: "Rehearsal documentation", type: "website" },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#08090a" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={geistMono.variable} suppressHydrationWarning>
      <body className="flex min-h-dvh flex-col font-sans">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
