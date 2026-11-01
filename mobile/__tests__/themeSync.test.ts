/**
 * Keeps the two halves of the design tokens in step.
 *
 * The palette exists twice, by necessity:
 *
 * - `global.css` `@theme` declares the CSS custom properties NativeWind
 *   compiles `className` against, so `bg-card` resolves from there.
 * - `src/theme/tokens.ts` holds the same values as plain strings for the
 *   places `className` cannot reach: a `ViewStyle` passed to a navigator,
 *   a colour handed to `ActivityIndicator`, a three.js material.
 *
 * Editing one and forgetting the other is invisible in code review and only
 * shows up as a component that is a shade off from its neighbours. This test
 * makes the drift fail here instead.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { colors } from "@/theme/tokens";

/**
 * Normalise a colour for comparison.
 *
 * The two files spell the same colour slightly differently -- `0.10` against
 * `0.1`, upper against lower hex -- so the comparison is on meaning rather
 * than on text.
 *
 * @param value - The raw colour string.
 * @returns A comparable form.
 */
function normalise(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "")
    .replace(/\.(\d*?)0+\)/g, (_, digits: string) =>
      digits.length === 0 ? ")" : `.${digits})`,
    );
}

/**
 * Turn a token name into the CSS custom property that carries it.
 *
 * `cardForeground` becomes `color-card-foreground`; the numbered chart ramp
 * (`chart1`) becomes `color-chart-1`.
 *
 * @param token - A key of {@link colors}.
 * @returns The custom property name without its leading dashes.
 */
function cssName(token: string): string {
  const kebab = token
    .replace(/([a-z])([A-Z])/g, "$1-$2")
    .replace(/^chart(\d)$/, "chart-$1")
    .toLowerCase();
  return `color-${kebab}`;
}

/** The declarations inside `@theme`, keyed by custom-property name. */
function parseTheme(css: string): Map<string, string> {
  const block = css.slice(css.indexOf("@theme"));
  const body = block.slice(block.indexOf("{") + 1, block.lastIndexOf("}"));
  const declarations = new Map<string, string>();

  for (const line of body.split("\n")) {
    const match = line.match(/^\s*--([a-z0-9-]+)\s*:\s*([^;]+);/i);
    if (match) declarations.set(match[1], match[2]);
  }

  return declarations;
}

describe("theme tokens", () => {
  const css = readFileSync(join(__dirname, "..", "global.css"), "utf8");
  const theme = parseTheme(css);

  it("declares a CSS custom property for every token", () => {
    for (const token of Object.keys(colors)) {
      expect(theme.has(cssName(token))).toBe(true);
    }
  });

  it("gives every token the same value in both files", () => {
    const drift: string[] = [];

    for (const [token, value] of Object.entries(colors)) {
      const fromCss = theme.get(cssName(token));
      if (fromCss === undefined) continue;
      if (normalise(fromCss) !== normalise(value)) {
        drift.push(`${token}: css ${fromCss} vs ts ${value}`);
      }
    }

    expect(drift).toEqual([]);
  });
});
