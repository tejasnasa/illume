/**
 * Dark theme palette. Mirrors the design tokens declared in
 * `client/src/app/globals.css`. Re-copy by hand if those tokens change.
 *
 * Values are sRGB hex / rgba because React Native's color parser does not
 * understand oklch or the CSS relative-color syntax. Each entry's source
 * oklch is preserved as an inline comment so the conversion is auditable.
 */

export const colors = {
  // oklch(0.141 0.005 285.823)
  background: "#09090b",
  // oklch(0.985 0 0)
  foreground: "#fafafa",
  // web value
  card: "#0e0e11",
  // oklch(0.985 0 0)
  cardForeground: "#fafafa",
  // web value
  popover: "#0e0e11",
  // oklch(0.985 0 0)
  popoverForeground: "#fafafa",
  // oklch(0.459 0.187 3.815)
  primary: "#a3004c",
  // oklch(0.971 0.014 343.198)
  primaryForeground: "#fdf2f8",
  // web value
  secondary: "#18181b",
  // oklch(0.985 0 0)
  secondaryForeground: "#fafafa",
  // oklch(0.274 0.006 286.033)
  muted: "#27272a",
  // oklch(0.705 0.015 286.067)
  mutedForeground: "#9f9fa9",
  // web value
  accent: "#f6339a",
  // web value
  accentForeground: "#fafafa",
  // web value
  destructive: "#ef4444",
  // web value
  success: "#22c55e",
  // oklch(1 0 0 / 10%)
  border: "rgba(255, 255, 255, 0.10)",
  // oklch(1 0 0 / 15%)
  input: "rgba(255, 255, 255, 0.15)",
  // web value
  ring: "#f6339a",
  // oklch(0.865 0.127 207.078)
  chart1: "#53eafd",
  // oklch(0.715 0.143 215.221)
  chart2: "#00b8db",
  // oklch(0.609 0.126 221.723)
  chart3: "#0092b8",
  // web value
  chart4: "#005f78",
  // web value
  chart5: "#104e64",
  // web value
  sidebar: "#0e0e11",
  // oklch(0.985 0 0)
  sidebarForeground: "#fafafa",
  // oklch(0.656 0.241 354.308)
  sidebarPrimary: "#f6339a",
  // oklch(0.971 0.014 343.198)
  sidebarPrimaryForeground: "#fdf2f8",
  // web value
  sidebarAccent: "#18181b",
  // oklch(0.985 0 0)
  sidebarAccentForeground: "#fafafa",
  // web value
  sidebarBorder: "rgba(255, 255, 255, 0.10)",
  // web value
  sidebarRing: "#f6339a",
  // web value
  warning: "#facc15",
  // web value
  selected: "#0078ff",
  // web value
  match: "#a855f7",
  // web value
  subtleForeground: "#71717a",
  // web value
  faintForeground: "#52525b",
  // web value
  borderStrong: "rgba(255, 255, 255, 0.20)",
} as const;

/** Type guard for any color string accepted by React Native's style parser. */
function isValidRNColor(value: string): boolean {
  if (typeof value !== "string" || value.length === 0) return false;
  // hex (3, 6, or 8 chars — 8-char includes alpha)
  if (/^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(value)) return true;
  // rgb / rgba
  if (/^rgba?\(/i.test(value)) return true;
  // hsl / hsla
  if (/^hsla?\(/i.test(value)) return true;
  // named colors — accept plain ASCII identifiers
  if (/^[a-z]+$/i.test(value)) return true;
  return false;
}

/**
 * Validate every token. Throws on the first invalid entry so a broken token
 * surfaces at startup instead of at the first render.
 */
export function assertValidColors(): void {
  for (const [name, value] of Object.entries(colors)) {
    if (!isValidRNColor(value)) {
      throw new Error(`Invalid color token "${name}": ${value}`);
    }
  }
}

export type ColorToken = keyof typeof colors;
export type ColorValue = (typeof colors)[ColorToken];
