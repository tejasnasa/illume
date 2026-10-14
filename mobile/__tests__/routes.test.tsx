/**
 * Route inventory smoke test. Each module under src/app/ is required,
 * which fails fast if a placeholder is missing or has the wrong shape
 * for expo-router. The actual render verification happens on-device,
 * where hot reload is the test surface.
 */
describe("route skeleton", () => {
  const routes = [
    "../src/app/_layout",
    "../src/app/index",
    "../src/app/onboarding",
    "../src/app/login",
    "../src/app/auth/callback",
    "../src/app/(app)/_layout",
    "../src/app/(app)/dashboard",
    "../src/app/(app)/settings",
    "../src/app/(app)/repo/[id]/_layout",
    "../src/app/(app)/repo/[id]/index",
    "../src/app/(app)/repo/[id]/explorer",
    "../src/app/(app)/repo/[id]/glossary",
    "../src/app/(app)/repo/[id]/graph",
  ];

  for (const route of routes) {
    it(`exports a default component from ${route}`, () => {
      const mod = require(route);
      expect(typeof mod.default).toBe("function");
    });
  }
});
