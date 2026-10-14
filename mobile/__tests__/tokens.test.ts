import { colors, assertValidColors } from "@/theme/tokens";

describe("theme tokens", () => {
  it("exports every token from the design palette", () => {
    expect(Object.keys(colors).sort()).toEqual(
      [
        "accent",
        "accentForeground",
        "background",
        "border",
        "card",
        "cardForeground",
        "chart1",
        "chart2",
        "chart3",
        "chart4",
        "chart5",
        "destructive",
        "foreground",
        "input",
        "muted",
        "mutedForeground",
        "popover",
        "popoverForeground",
        "primary",
        "primaryForeground",
        "ring",
        "secondary",
        "secondaryForeground",
        "sidebar",
        "sidebarAccent",
        "sidebarAccentForeground",
        "sidebarBorder",
        "sidebarForeground",
        "sidebarPrimary",
        "sidebarPrimaryForeground",
        "sidebarRing",
        "success",
      ].sort(),
    );
  });

  it("every token is a string the React Native color parser accepts", () => {
    assertValidColors();
  });

  it("assertValidColors throws when a token is invalid", () => {
    const original = colors.primary;
    (colors as Record<string, string>).primary = "oklch(0.5 0 0)";
    expect(() => assertValidColors()).toThrow(/primary/);
    (colors as Record<string, string>).primary = original;
  });
});
