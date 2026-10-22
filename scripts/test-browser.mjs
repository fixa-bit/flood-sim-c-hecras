import { mkdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const project = fileURLToPath(new URL("../", import.meta.url));
const temporary = join(project, "workspace", "temp", "browser-tests");
const cache = join(temporary, "transform-cache");
mkdirSync(cache, { recursive: true });
const result = spawnSync(
  process.execPath,
  [
    join(project, "node_modules", "@playwright", "test", "cli.js"),
    "test",
    ...process.argv.slice(2),
  ],
  {
    cwd: project,
    stdio: "inherit",
    env: {
      ...process.env,
      TEMP: temporary,
      TMP: temporary,
      TMPDIR: temporary,
      PWTEST_CACHE_DIR: cache,
    },
  },
);
if (result.error) console.error(result.error.message);
process.exit(result.status ?? 1);
