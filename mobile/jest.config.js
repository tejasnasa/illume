// Extend the jest-expo preset's transformIgnorePatterns so TypeScript
// sources inside expo-modules-core and similar packages are compiled.
const preset = require("jest-expo/jest-preset");

module.exports = {
  ...preset,
  setupFiles: ["<rootDir>/jest.setup.js", ...(preset.setupFiles ?? [])],
  moduleNameMapper: {
    ...(preset.moduleNameMapper ?? {}),
    "^@/(.*)$": "<rootDir>/src/$1",
    // ``global.css`` is wired into the runtime by NativeWind's Metro
    // hook on device; in jest we substitute an empty module so the
    // import does not blow up the resolver. The className itself is
    // identity-mapped by the ``nativewind`` jest mock in
    // ``jest.setup.js``.
    "\\.(css|scss|sass)$": "<rootDir>/__mocks__/styleMock.js",
  },
  testPathIgnorePatterns: ["/node_modules/", "/e2e/"],
};
