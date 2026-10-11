"use client";

import dynamic from "next/dynamic";
import type { ReactNode } from "react";
import { RootProvider } from "fumadocs-ui/provider/next";

// loaded when search is first opened, so pages do not pay for it
const SearchDialog = dynamic(() => import("./search-dialog"), { ssr: false });

export function Providers({ children }: { children: ReactNode }) {
  return (
    <RootProvider
      search={{ SearchDialog, preload: false }}
      theme={{ defaultTheme: "system", enableSystem: true, hotKey: false }}
    >
      {children}
    </RootProvider>
  );
}
