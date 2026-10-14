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
  // oklch(0.21 0.006 285.885)
  card: "#18181b",
  // oklch(0.985 0 0)
  cardForeground: "#fafafa",
  // oklch(0.21 0.006 285.885)
  popover: "#18181b",
  // oklch(0.985 0 0)
  popoverForeground: "#fafafa",
  // oklch(0.459 0.187 3.815)
  primary: "#a3004c",
  // oklch(0.971 0.014 343.198)
  primaryForeground: "#fdf2f8",
  // oklch(0.274 0.006 286.033)
  secondary: "#27272a",
  // oklch(0.985 0 0)
  secondaryForeground: "#fafafa",
  // oklch(0.274 0.006 286.033)
  muted: "#27272a",
  // oklch(0.705 0.015 286.067)
  mutedForeground: "#9f9fa9",
  // oklch(0.274 0.006 286.033)
  accent: "#27272a",
  // oklch(0.985 0 0)
  accentForeground: "#fafafa",
  // oklch(0.704 0.191 22.216)
  destructive: "#ff6467",
  // oklch(0.75 0.16 155)
  success: "#42cb80",
  // oklch(1 0 0 / 10%)
  border: "rgba(255, 255, 255, 0.10)",
  // oklch(1 0 0 / 15%)
  input: "rgba(255, 255, 255, 0.15)",
  // oklch(0.552 0.016 285.938)
  ring: "#71717b",
  // oklch(0.865 0.127 207.078)
  chart1: "#53eafd",
  // oklch(0.715 0.143 215.221)
  chart2: "#00b8db",
  // oklch(0.609 0.126 221.723)
  chart3: "#0092b8",
  // oklch(0.52 0.105 223.128)
  chart4: "#007595",
  // oklch(0.45 0.085 224.283)
  chart5: "#005f78",
  // oklch(0.21 0.006 285.885)
  sidebar: "#18181b",
  // oklch(0.985 0 0)
  sidebarForeground: "#fafafa",
  // oklch(0.656 0.241 354.308)
  sidebarPrimary: "#f6339a",
  // oklch(0.971 0.014 343.198)
  sidebarPrimaryForeground: "#fdf2f8",
  // oklch(0.274 0.006 286.033)
  sidebarAccent: "#27272a",
  // oklch(0.985 0 0)
  sidebarAccentForeground: "#fafafa",
  // oklch(1 0 0 / 10%)
  sidebarBorder: "rgba(255, 255, 255, 0.10)",
  // oklch(0.552 0.016 285.938)
  sidebarRing: "#71717b",
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
