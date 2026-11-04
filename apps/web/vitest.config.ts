import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: { alias: { "@": new URL("./", import.meta.url).pathname } },
  test: { include: ["lib/**/*.test.ts", "components/**/*.test.tsx"], environment: "node" },
});
