/**
 * Guards the one ``EXPO_PUBLIC_`` read in the app.
 *
 * Expo substitutes these values by matching a literal ``process.env.X`` member
 * expression in the AST before the bundle is built. Any expression that wraps
 * ``process.env`` -- a type cast, a destructure, an index signature -- compiles
 * fine and passes every other test, then reads ``undefined`` on a device and
 * takes the release build down at launch with "EXPO_PUBLIC_BACKEND_URL is not
 * set". Nothing else catches that, because the jest environment still has a
 * real ``process.env``.
 *
 * This reads the source rather than the bundle, so it runs in milliseconds.
 */
import { readFileSync } from "fs";
import { join } from "path";

const CLIENT_SOURCE = readFileSync(
  join(__dirname, "..", "src", "api", "client.ts"),
  "utf8",
);

describe("EXPO_PUBLIC_BACKEND_URL", () => {
  it("is read as a literal member expression", () => {
    expect(CLIENT_SOURCE).toContain(
      "process.env.EXPO_PUBLIC_BACKEND_URL",
    );
  });

  it("is not read through a wrapper Expo cannot substitute", () => {
    // Anything shaped `(process.env as T).EXPO_PUBLIC_...`,
    // `process.env["EXPO_PUBLIC_..."]` or `{ EXPO_PUBLIC_... } = process.env`.
    expect(CLIENT_SOURCE).not.toMatch(/[)\]]\s*\.\s*EXPO_PUBLIC_/);
    expect(CLIENT_SOURCE).not.toMatch(/\[\s*["'`]EXPO_PUBLIC_/);
    expect(CLIENT_SOURCE).not.toMatch(/=\s*process\.env\s*[;,)]/);
  });
});
