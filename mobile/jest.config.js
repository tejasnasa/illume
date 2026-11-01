// Extend the jest-expo preset's transformIgnorePatterns so TypeScript
// sources inside expo-modules-core and similar packages are compiled.
const preset = require("jest-expo/jest-preset");

module.exports = {
  ...preset,
  setupFiles: ["<rootDir>/jest.setup.js", ...(preset.setupFiles ?? [])],
  setupFilesAfterEnv: [
    "<rootDir>/jest.after-env.js",
    ...(preset.setupFilesAfterEnv ?? []),
  ],
  // ``d3-force-3d`` and the ``d3-*`` packages it pulls in ship as ES
  // modules only, so they have to be compiled rather than skipped the way
  // the rest of node_modules is. The preset's pattern is a single
  // alternation of the packages that are allowed through, so the new
  // packages are added to it rather than appended as a second pattern --
  // two patterns are OR-ed, and a second one would re-ignore everything
  // the first one let through.
  transformIgnorePatterns: (preset.transformIgnorePatterns ?? []).map(
    (pattern) =>
      typeof pattern === "string" && pattern.includes("node_modules/(?!(")
        ? pattern.replace(
            "/node_modules/(?!(",
            "/node_modules/(?!(d3-force-3d|d3-binarytree|d3-dispatch|d3-octree|d3-quadtree|d3-timer|",
          )
        : pattern,
  ),
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
  // React Query keeps a garbage-collection timer per cache entry, and the
  // default window is five minutes. Nothing in a test run needs it, but it
  // does keep the event loop alive long after the last assertion, so the
  // process would sit there for five minutes before exiting.
  forceExit: true,
};
