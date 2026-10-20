# Illume Mobile

React Native / Expo port of the Illume web client.

## Layout

```
mobile/
└── src/
    ├── app/                expo-router routes
    │   ├── _layout.tsx     root: providers, fonts, theme
    │   ├── onboarding.tsx  replaces the marketing landing page
    │   ├── login.tsx
    │   ├── auth/callback.tsx   deep-link target for OAuth
    │   └── (app)/              protected route group
    │       ├── _layout.tsx
    │       ├── dashboard.tsx
    │       ├── settings.tsx
    │       └── repo/[id]/
    │           ├── _layout.tsx
    │           ├── index.tsx
    │           ├── explorer.tsx
    │           ├── glossary.tsx
    │           └── graph.tsx
    ├── components/         shared RN components
    ├── ui/                 primitives: Button, Input, Sheet, Modal…
    ├── hooks/              ports of client/src/hooks/ (useAuth lives here)
    ├── lib/                framework-agnostic helpers (tokenStore, authCallback)
    ├── api/                one client, token-injecting
    ├── types/              copied from client/src/types/
    ├── graph/              the 3D renderer (graph milestone)
    └── theme/tokens.ts     design tokens (sRGB hex / rgba)
├── e2e/                    Maestro flows
└── __tests__/              jest specs
```

## Running

```bash
npm install
npx expo run:android      # development build on a connected device
npx expo start --dev-client
```

For the first install use `npx eas build --profile development --platform android`
to produce a dev client that has the exact native modules pinned in
`package.json`. Hot reload works inside that build via `npx expo start`.

### `npx eas` needs the CLI installed locally

**`npx eas build` fails with "could not determine executable to run"** if
`eas-cli` is not a dependency. There is an unrelated package called
`eas` on npm ("Embedded Async Simple Javascript templating", v0.1.0)
that ships no binary, and `npx` resolves _that_ one. The real CLI is
`eas-cli`, which provides the `eas` binary.

`eas-cli` is therefore a devDependency here, so `npx eas ...` resolves
to `node_modules/.bin/eas` rather than the placeholder. If you ever see
the error above, the fix is `npm install` (which restores the local
binary) -- not a different command.

## Testing

```bash
npm test                # runs __tests__/ via jest-expo
```

The `tokens.test.ts` spec asserts every token in `src/theme/tokens.ts` is a
string the React Native color parser accepts; the `routes.test.tsx` spec
imports every placeholder route file so a missing screen fails the build.
Auth-specific specs live alongside:

- `tokenStore.test.ts` -- round-trips through the encrypted-storage adapter.
- `authCallback.test.ts` -- parses the deep-link URL and assembles the
  authorize URL.
- `authGuard.test.tsx` -- exercises the `useAuth` state machine (loading,
  hydrated, expired, network failure, sign-in / sign-out).
- `authCallbackScreen.test.tsx` -- mounts the callback screen end-to-end
  with a mocked router to assert the parse -> store -> redirect sequence.

## Deep links

The `illume` URL scheme is registered in `app.json`. OAuth's return path is
`illume://auth/callback` -- the backend's allowlist (`OAUTH_REDIRECT_ALLOWLIST`
on the server) must contain that exact URI for the redirect to land back in
the app.

## Auth flow

The login screen opens the backend's `/api/v1/auth/github?state=...` URL in
a system browser via `expo-web-browser`; GitHub walks the user through the
consent screen, the backend exchanges the code, and the resulting redirect
carries the token in the query string of the deep-link URL. The callback
screen parses the URL, persists the token via `expo-secure-store`, and
navigates to the dashboard. The root layout's `(app)/_layout.tsx` enforces
the inverse -- a missing or invalid token redirects to `/login`.

The token stored on the device is also the one sent as
`Authorization: Bearer <token>` on every API call, decrypted by the backend's
`AuthMiddleware` once cookie auth is bypassed.

## Native dependencies in this build

**Every native module the whole plan needs is installed and linked now**, so
the phases after this do not require another rebuild. The list below is
what the Android build actually contains; `node scripts/check-native-linking.mjs`
verifies it against the same resolution Gradle uses.

| Package                                     | Used by                                         |
| ------------------------------------------- | ----------------------------------------------- |
| `expo-secure-store`                         | Encrypted token storage                         |
| `expo-auth-session` + `expo-web-browser`    | GitHub OAuth flow                               |
| `expo-application` + `expo-crypto`          | OAuth state params (transitive of auth-session) |
| `@react-native-async-storage/async-storage` | Non-secret prefs                                |
| `expo-dev-client`                           | Metro handshake, dev menu                       |
| `expo-splash-screen`                        | The launch screen (Phase 1)                     |
| `react-native-svg`                          | The git graph's rail lines and commit nodes     |
| `expo-gl`                                   | The 3D dependency graph (Phase 9)               |
| `three` (**pinned `0.162.0`**)              | The 3D scene graph (Phase 9)                    |
| `d3-force-3d`                               | The 3D layout force simulation (Phase 9)        |
| `expo-blur`                                 | The glass-card backdrop (Phase 6)               |
| `expo-file-system`                          | Writing the export file (Phase 12)              |
| `expo-sharing`                              | The share sheet for exports (Phase 12)          |
| `expo-notifications` + `expo-device`        | Push on ingest completion (Phase 13)            |
| `react-native-pager-view`                   | The onboarding carousel (Phase 14)              |
| `expo-build-properties`                     | Release-build Gradle settings (config plugin)   |

`three` is pinned to `0.162.0` because r163 dropped WebGL 1 support and
`expo-gl` provides a WebGL 1 context. Bumping it breaks the graph -- see
the plan's §5.2.

### Adding a native module means rebuilding the dev client

**A native module that is in `package.json` but not in the installed APK
crashes at runtime, not at build time.** The symptom is a `ViewManager`
error naming the missing component, e.g.:

```
Can't find ViewManager 'RNSVGPath' nor 'RCTRNSVGPath' in ViewManagerRegistry
```

The JS bundle is served by Metro, so the new code loads fine -- but the
_native_ half of the module was never compiled into the APK, so the
component has no view manager to attach to. The fix is a new dev build:

```bash
npx eas build --profile development --platform android
```

Then reinstall that APK on the device. Hot reload cannot fix this: no
amount of reloading will add native code that was not compiled in.

`npx expo run:android` does the same thing locally, but it needs the
Android SDK and a connected device.

### The `typescript` override -- do not remove it

`@expo/require-utils` declares an **optional** peer dependency on
`typescript@^5 || ^6 || ^7`. Without a constraint, npm resolves it to
the newest match -- TypeScript **7**, the native-compiler release --
which drags in twenty `@typescript/typescript-<platform>` binaries (one
per OS/arch) and a nested `typescript@7.0.2`.

npm marks that whole subtree `extraneous`, because the peer is optional
and the project already pins `typescript@5.4.5` at the root. But
`npm ci` still tries to install it, and dies on the first binary whose
platform does not match the builder:

```
npm error code EBADPLATFORM
npm error notsup Unsupported platform for @typescript/typescript-aix-ppc64@7.0.2:
npm error notsup wanted {"os":"aix","cpu":"ppc64"} (current: {"os":"linux","cpu":"x64"})
```

The `overrides` block in `package.json` pins that peer to the same
TypeScript 5 the project uses:

```json
"overrides": { "typescript": "~5.4.0" }
```

With it, the TypeScript 7 subtree is never resolved, the lockfile has
**zero** `extraneous` entries, and `npm ci` succeeds on any platform.
Removing the override reintroduces the failure on the EAS builder.

### Adding a dependency

`npm install <pkg>` is all that is needed. The `typescript` override
above is what makes that safe -- without it, npm's re-resolution drags
the TypeScript 7 tree in and the builder's `npm ci` fails on the
platform check. With it, `npm install` is stable: it leaves the
lockfile byte-identical.

Check the result with:

```bash
npm ci --dry-run   # the same consistency validation the EAS builder runs
```

It should exit 0 with no `Missing:` or `EUSAGE` errors.

## App icon

The launcher icon is the web client's brand mark: Phosphor's
`StarFour` at `weight="fill"`, in the app's brand cyan on the app's
background colour. The assets are generated, not hand-drawn:

```bash
python scripts/generate_assets.py
```

That writes `assets/icon.png` (the launcher icon), `assets/adaptive-icon.png`
(the Android adaptive foreground, sized inside the safe circle),
`assets/splash.png`, `assets/favicon.png`, and
`assets/notification-icon.png`. `app.json` points at all of them.
