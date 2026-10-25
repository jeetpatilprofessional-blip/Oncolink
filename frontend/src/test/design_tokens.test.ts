import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

/**
 * Authoritative design tokens from DESIGN.md section 3.
 * Lowercase normalized hex codes.
 */
const ALLOWED_HEX_TOKENS = new Set([
  "#f5f7f6", // paper
  "#18242c", // ink
  "#d5dad8", // rule
  "#4a4c4e", // viewer
  "#4b2e83", // gentian
  "#ffffff", // white
  "#b42318", // urgent
  "#b7791f", // soon
  "#2f7d57", // routine
  "#52627a", // uncertain
]);

function normalizeHex(hex: string): string {
  const lower = hex.toLowerCase();
  if (lower.length === 4) {
    // Expand 3-digit hex like #fff to #ffffff
    return "#" + lower[1] + lower[1] + lower[2] + lower[2] + lower[3] + lower[3];
  }
  return lower;
}

function getAllFiles(dirPath: string, arrayOfFiles: string[] = []): string[] {
  const entries = fs.readdirSync(dirPath, { withFileTypes: true });

  for (const entry of entries) {
    const fullPath = path.join(dirPath, entry.name);
    if (entry.isDirectory()) {
      getAllFiles(fullPath, arrayOfFiles);
    } else {
      arrayOfFiles.push(fullPath);
    }
  }

  return arrayOfFiles;
}

describe("Design Token Color Enforcement", () => {
  it("verifies that all colors in frontend/src use authoritative design tokens", () => {
    const srcDir = path.resolve(__dirname, "..");
    const files = getAllFiles(srcDir);

    const hexRegex = /#(?:[0-9a-fA-F]{3,8})\b/g;
    const rgbRegex = /rgba?\([^)]+\)/g;

    const violations: { file: string; line: number; match: string; text: string }[] = [];

    for (const filePath of files) {
      const fileName = path.basename(filePath);

      // Exclude index.css and token definition/test files
      if (fileName === "index.css" || fileName.toLowerCase().includes("token")) {
        continue;
      }

      // Only scan source and test files
      if (!/\.(tsx?|jsx?|html)$/.test(fileName)) {
        continue;
      }

      const content = fs.readFileSync(filePath, "utf-8");
      const lines = content.split("\n");

      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        if (!line) continue;

        // Skip comments or ignore lines if needed
        const trimmed = line.trim();
        if (trimmed.startsWith("//") || trimmed.startsWith("/*") || trimmed.startsWith("*")) {
          continue;
        }

        // Check for hex matches
        const hexMatches = line.match(hexRegex);
        if (hexMatches) {
          for (const match of hexMatches) {
            const normalized = normalizeHex(match);
            if (!ALLOWED_HEX_TOKENS.has(normalized)) {
              violations.push({
                file: path.relative(srcDir, filePath),
                line: i + 1,
                match,
                text: trimmed,
              });
            }
          }
        }

        // Check for rgb/rgba matches
        const rgbMatches = line.match(rgbRegex);
        if (rgbMatches) {
          for (const match of rgbMatches) {
            violations.push({
              file: path.relative(srcDir, filePath),
              line: i + 1,
              match,
              text: trimmed,
            });
          }
        }
      }
    }

    if (violations.length > 0) {
      console.error(
        "Design token color violations detected:\n" +
          violations
            .map((v) => `  ${v.file}:${v.line} -> ${v.match} in "${v.text}"`)
            .join("\n")
      );
    }

    expect(violations).toEqual([]);
  });
});
