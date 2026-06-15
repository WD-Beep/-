import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

/** @type {string | undefined} */
let srcRoot;

export async function initialize({ srcRoot: root }) {
  srcRoot = root;
}

/** @param {string} specifier */
function resolveAlias(specifier) {
  if (!specifier.startsWith("@/") || !srcRoot) {
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

/** @type {import("node:module").ResolveHook} */
export async function resolve(specifier, context, nextResolve) {
  const mapped = resolveAlias(specifier);
  if (mapped) {
    return nextResolve(mapped, context);
  }
  return nextResolve(specifier, context);
}
