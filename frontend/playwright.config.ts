import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  timeout: 60000,
  workers: 1,
  use: {
    baseURL: "https://localhost:3443",
    ignoreHTTPSErrors: true,
    channel: "msedge",
    headless: true,
  },
  reporter: [
    ["list"],
    ["json", { outputFile: "../evidence/browser-results.json" }],
  ],
  outputDir: "../runtime/browser-test-results",
});
