// Tailwind v4 + PostCSS pipeline for NativeWind v5.
//
// Expo 57 discovers ``postcss.config.js`` and ``postcss.config.mjs`` but
// not ``postcss.config.cjs``; keep this filename as-is.
export default {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};
