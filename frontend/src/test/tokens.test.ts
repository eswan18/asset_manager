import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

// Vitest runs from frontend/.
const SRC = join(process.cwd(), "src");
// The only place colors are written down.
const TOKENS = "styles/tokens.css";

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

describe("design tokens", () => {
  it("are the only colors: components name tokens, never values", () => {
    const offenders: string[] = [];
    for (const path of files(SRC)) {
      const rel = relative(SRC, path);
      if (rel === TOKENS || rel.endsWith(".test.ts")) continue;
      if (!/\.(tsx?|css)$/.test(rel)) continue;
      const text = readFileSync(path, "utf8");
      const found = text.match(
        /#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|\brgba?\(|\bhsla?\(|\boklch\(/g,
      );
      if (found) offenders.push(`${rel}: ${found.join(", ")}`);
    }
    expect(offenders).toEqual([]);
  });
});
