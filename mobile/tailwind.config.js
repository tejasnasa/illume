/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,jsx,ts,tsx}",
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  presets: [require("nativewind/preset")],
  theme: {
    extend: {
      colors: {
        background: "#09090b",
        foreground: "#fafafa",
        card: {
          DEFAULT: "#18181b",
          foreground: "#fafafa",
        },
        popover: {
          DEFAULT: "#18181b",
          foreground: "#fafafa",
        },
        primary: {
          DEFAULT: "#a3004c",
          foreground: "#fdf2f8",
        },
        secondary: {
          DEFAULT: "#27272a",
          foreground: "#fafafa",
        },
        muted: {
          DEFAULT: "#27272a",
          foreground: "#9f9fa9",
        },
        accent: {
          DEFAULT: "#27272a",
          foreground: "#fafafa",
        },
        destructive: "#ff6467",
        success: "#42cb80",
        border: "rgba(255, 255, 255, 0.10)",
        input: "rgba(255, 255, 255, 0.15)",
        ring: "#71717b",
        chart: {
          1: "#53eafd",
          2: "#00b8db",
          3: "#0092b8",
          4: "#007595",
          5: "#005f78",
        },
        sidebar: {
          DEFAULT: "#18181b",
          foreground: "#fafafa",
          primary: {
            DEFAULT: "#f6339a",
            foreground: "#fdf2f8",
          },
          accent: {
            DEFAULT: "#27272a",
            foreground: "#fafafa",
          },
          border: "rgba(255, 255, 255, 0.10)",
          ring: "#71717b",
        },
      },
    },
  },
  plugins: [],
};
