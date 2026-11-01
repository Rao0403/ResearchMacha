import { defineConfig, devices } from "@playwright/test";

const viewports = [
  { name: "chromium-1440", width: 1440, height: 900 },
  { name: "chromium-1280", width: 1280, height: 800 },
  { name: "chromium-1024", width: 1024, height: 768 },
  { name: "chromium-mobile", width: 390, height: 844 },
];

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: viewports.map(({ name, width, height }) => ({
    name,
    use: {
      ...devices["Desktop Chrome"],
      viewport: { width, height },
    },
  })),
  webServer: {
    command: "node ./node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4173",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
    gracefulShutdown: { signal: "SIGINT", timeout: 500 },
  },
});
