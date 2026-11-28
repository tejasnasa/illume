/**
 * The font files the app loads at start-up.
 *
 * Mirrors the two faces the web client uses: Geist Sans for text and Geist
 * Pixel Square for labels. React Native selects a weight by family name, so
 * each weight is its own entry, and `font-sans-*` / `font-pixel` in
 * `global.css` name the same strings.
 */

/** Family name to bundled font file. */
export const FONT_FILES = {
  "Geist-Regular": require("../../assets/fonts/Geist-Regular.ttf"),
  "Geist-Medium": require("../../assets/fonts/Geist-Medium.ttf"),
  "Geist-SemiBold": require("../../assets/fonts/Geist-SemiBold.ttf"),
  "Geist-Bold": require("../../assets/fonts/Geist-Bold.ttf"),
  "GeistPixel-Square": require("../../assets/fonts/GeistPixel-Square.ttf"),
} as const;

/** Family name used for text labels in `style` objects. */
export const PIXEL_FONT = "GeistPixel-Square";
/** Family name used for body text in `style` objects. */
export const SANS_FONT = "Geist-Regular";
