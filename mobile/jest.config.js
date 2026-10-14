// Extend the jest-expo preset's transformIgnorePatterns so TypeScript
// sources inside expo-modules-core and similar packages are compiled.
const preset = require("jest-expo/jest-preset");

module.exports = {
  ...preset,
  setupFiles: ["<rootDir>/jest.setup.js", ...(preset.setupFiles ?? [])],
  moduleNameMapper: {
    ...(preset.moduleNameMapper ?? {}),
    "^@/(.*)$": "<rootDir>/src/$1",
  },
  testPathIgnorePatterns: ["/node_modules/", "/e2e/"],
};
