import { createFromSource } from "fumadocs-core/search/server";
import { source } from "@/lib/source";

// The search index as one static file. The browser downloads it the first time search is opened.
export const { staticGET: GET } = createFromSource(source);

// a static export serves this as a file written at build time
export const dynamic = "force-static";
