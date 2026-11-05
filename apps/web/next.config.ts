import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The isolated E2E stack builds into its own directory so it can run beside `make dev` (finding 10).
  distDir: process.env.OPSPILOT_WEB_DIST_DIR || ".next",
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
