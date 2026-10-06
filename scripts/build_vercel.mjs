import { cpSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { outputConfig, runtimeOrigin } from "./vercel_config.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
const origin = runtimeOrigin(process.env.PARALLAX_RUNTIME_URL || "");
const mode = origin ? "cloud" : "hosted";
const build = spawnSync("npm", ["exec", "--", "tsc", "--noEmit"], {
  cwd: resolve(root, "studio"),
  stdio: "inherit",
});
if (build.status !== 0) process.exit(build.status || 1);
const bundle = spawnSync(
  "npm",
  ["exec", "--", "vite", "build", "--mode", mode],
  { cwd: resolve(root, "studio"), stdio: "inherit" },
);
if (bundle.status !== 0) process.exit(bundle.status || 1);
const output = resolve(root, ".vercel/output");
rmSync(output, { recursive: true, force: true });
mkdirSync(output, { recursive: true });
cpSync(resolve(root, "studio/dist"), resolve(output, "static"), {
  recursive: true,
});
writeFileSync(
  resolve(output, "config.json"),
  JSON.stringify(outputConfig(origin), null, 2) + "\n",
);
console.log(
  `Prepared Vercel Build Output API v3: ${mode === "cloud" ? "Railway-backed Studio" : "local Studio entry"}.`,
);
