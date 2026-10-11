import type { NextConfig } from "next";
import { createMDX } from "fumadocs-mdx/next";

const withMDX = createMDX();

const nextConfig: NextConfig = {
  // The site is static files, so it stays up when the product's servers are down (a requirement of the docs plan).
  // The starter's cacheComponents and partialPrefetching are off on purpose: they need a running server, and Next
  // rejects them next to the `dynamic = "force-static"` that an export requires on the routes that write files
  // (the search index, llms.txt, each page's Markdown).
  output: "export",
  images: { unoptimized: true },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default withMDX(nextConfig);
