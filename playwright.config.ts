import { defineConfig } from "@playwright/test";
import { existsSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";

const browserTemp = resolve("workspace/temp/browser-tests");
mkdirSync(browserTemp, { recursive: true });
process.env.TEMP = browserTemp;
process.env.TMP = browserTemp;

if (
  !process.env.PLAYWRIGHT_BROWSERS_PATH &&
  existsSync("workspace/tools/browsers")
)
  process.env.PLAYWRIGHT_BROWSERS_PATH = resolve("workspace/tools/browsers");

export default defineConfig({
  testDir: "./tests/browser",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: {
    baseURL: "http://127.0.0.1:5174",
    headless: true,
    screenshot: "only-on-failure",
    launchOptions: {
      args: ["--enable-unsafe-swiftshader", "--disable-gpu-sandbox"],
    },
  },
  reporter: "list",
  timeout: 60000,
});
