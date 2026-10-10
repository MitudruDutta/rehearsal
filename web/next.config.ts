import type { NextConfig } from "next";

// Production: a static export served by the Rehearsal API on the same origin
// (session cookies and SSE stay same-origin). Development: `next dev` (port 3000) proxies /v1 and /downloads to the API on 7800.
const dev = process.env.NODE_ENV === "development";

const config: NextConfig = {
  ...(dev ? {} : { output: "export" }),
  trailingSlash: true,
  images: { unoptimized: true },
  ...(dev
    ? {
        rewrites: async () => [
          { source: "/v1/:path*", destination: "http://127.0.0.1:7800/v1/:path*" },
          { source: "/downloads/:path*", destination: "http://127.0.0.1:7800/downloads/:path*" },
        ],
      }
    : {}),
};

export default config;
