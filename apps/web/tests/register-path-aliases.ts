/**
 * Node test preload: resolve `@/` to `apps/web/src/` (mirrors tsconfig paths).
 * Import this module first in tests that load source files using `@/` aliases.
 */
import fs from "node:fs";
import path from "node:path";
import { register } from "node:module";
import { pathToFileURL, fileURLToPath } from "node:url";

const srcRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src");

register("./path-alias-hook.js", import.meta.url, {
  data: { srcRoot },
});

export function resolveAlias(specifier: string): string | null {
  if (!specifier.startsWith("@/")) {
    return null;
  }
  const rel = specifier.slice(2);
  const base = path.join(srcRoot, rel);
  for (const suffix of ["", ".ts", ".tsx", "/index.ts", "/index.tsx"]) {
    const candidate = base + suffix;
    if (fs.existsSync(candidate)) {
      return pathToFileURL(candidate).href;
    }
  }
  return null;
}
