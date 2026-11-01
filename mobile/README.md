# Illume Mobile

React Native / Expo port of the Illume web client.

## Layout

```
mobile/
└── src/
    ├── app/                expo-router routes
    │   ├── _layout.tsx     root: providers, query client, error boundary
    │   ├── index.tsx       cold-start decision (dashboard / carousel / login)
    │   ├── +not-found.tsx  unknown / stale deep links
    │   ├── onboarding.tsx  replaces the marketing landing page
    │   ├── login.tsx
    │   ├── auth/callback.tsx   deep-link target for OAuth (Android)
    │   └── (app)/              protected route group
    │       ├── _layout.tsx
    │       ├── dashboard.tsx
    │       ├── settings.tsx   and settings/{ai,auto-update,danger,contact}
    │       ├── repo-picker.tsx
    │       └── repo/[id]/
    │           ├── _layout.tsx
    │           ├── index.tsx     the overview, and the live ingest view
    │           ├── explorer.tsx  the file tree
    │           ├── glossary.tsx
    │           ├── graph.tsx    the 3D dependency graph
    │           └── chat.tsx
    ├── components/         shared RN components (screens' building blocks)
    ├── ui/                 small presentational pieces (RepoCard, MarkdownText,
    │                       status badge, tab bar, floating action button…)
    ├── hooks/              ports of client/src/hooks/ (useAuth lives here)
    ├── lib/                framework-agnostic helpers (tokenStore, authCallback)
    ├── api/                one client, token-injecting
    ├── types/              copied from client/src/types/
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

## Building

Three EAS profiles, in `eas.json`:

| Profile       | What it produces                                   |
| ------------- | -------------------------------------------------- |
| `development` | A dev client for `npx expo start --dev-client`.    |
| `preview`     | An APK, installable on any device without a store. |
| `production`  | A release build, versioned by EAS.                 |

```bash
npx eas build --profile preview --platform android
```

`eas-cli` is a devDependency so `npx eas ...` resolves to the real binary
rather than the unrelated `eas` package on npm -- see the note below.

### `EXPO_PUBLIC_BACKEND_URL` must be set for preview and production builds

`.env` is gitignored and EAS does not upload it, so a build that does not set
this variable has no backend address. Development builds fall back to
`http://10.0.2.2:8000` (the Android emulator's host alias); release builds
refuse to start and say so, because that address resolves to nothing on a
real device.

The `preview` and `production` profiles in `eas.json` already point at the
deployed API, `https://illume-api.tejasnasa.me`. The `development` profile
deliberately has no value: a dev client loads its bundle from Metro, so it
picks up the local `.env` instead.

`eas env:create`/`eas env:list` manage the dashboard side if the URL ever
needs to move without a commit.

### Building an installable APK against the deployed backend

```bash
npx eas login                       # once per machine
npx eas build --profile preview --platform android
```

`preview` produces an APK (`distribution: internal`, `buildType: apk`) and
prints a download link and a QR code. Install it, sign in with GitHub, and
the app talks to the production API -- no local server, no Metro.

The first line of the build log reports the archive size. It should be a few
megabytes. If it is hundreds of megabytes or more, `.easignore` is not
matching — EAS archives the git repository root, and an ignore rule whose
line ends in a carriage return matches nothing. `.gitattributes` pins that
file to LF for exactly this reason.

Three things have to be true for that sign-in to land:

1. The backend's `OAUTH_REDIRECT_ALLOWLIST` contains `illume://auth/callback`
   exactly. If it does not, the callback redirects to `FRONTEND_URL` (the
   web app) instead and the phone never receives the token.
2. The phone can reach `https://illume-api.tejasnasa.me` (HTTPS, so the
   ingest WebSocket becomes `wss://` automatically).
3. The device clock is roughly right -- the token is a JWT and a badly
   skewed clock fails validation.

Push notifications are the one feature that will not work from a `preview`
build until `google-services.json` is added (see the next section).

### Push notifications need a Firebase configuration

Remote push on Android goes through Firebase Cloud Messaging, so a
**release** build needs a `google-services.json` at the project root and
`android.googleServicesFile` pointing at it in `app.json`.

Without it, `getExpoPushTokenAsync` fails on Android and no token is ever
registered -- the app works, it just never pushes. A development build
works without it: Expo's own push service is used for local development.

The permission is asked for **after the first successful ingest**, not at
launch. A cold permission prompt gets denied, because nobody knows what
they are agreeing to yet.

## Testing

```bash
npm test                # runs __tests__/ via jest-expo
npm run typecheck       # tsc --noEmit
```

There is no linter in this package yet: the web client's ESLint config does
not apply to React Native, and no React Native config has been added. Do not
add a `lint` script that does not lint.

The `tokens.test.ts` spec asserts every token in `src/theme/tokens.ts` is a
string the React Native color parser accepts; the `routes.test.tsx` spec
imports every route file so a missing screen fails the build.
Auth-specific specs live alongside:

- `tokenStore.test.ts` -- round-trips through the encrypted-storage adapter.
- `authCallback.test.ts` -- parses the deep-link URL and assembles the
  authorize URL.
- `authGuard.test.tsx` -- exercises the `useAuth` state machine (loading,
  hydrated, expired, network failure, sign-in / sign-out).
- `authCallbackScreen.test.tsx` -- mounts the callback screen end-to-end
  with a mocked router to assert the parse -> store -> redirect sequence.

The end-to-end flows live in `e2e/` and need a real device, a running
backend, and an account signed in by hand -- see `e2e/README.md`.

## Deep links

The `illume` URL scheme is registered in `app.json`. OAuth's return path is
`illume://auth/callback` -- the backend's allowlist (`OAUTH_REDIRECT_ALLOWLIST`
on the server) must contain that exact URI for the redirect to land back in
the app.

## Auth flow

The login screen opens the backend's `/api/v1/auth/github?state=...` URL in
a system browser via `expo-web-browser`; GitHub walks the user through the
consent screen, the backend exchanges the code, and the resulting redirect
carries the token in the query string of the deep-link URL.

The redirect comes back **two different ways depending on the platform**:

- **Android** delivers it as a `Linking` event, which mounts
  `src/app/auth/callback.tsx`; that screen parses the URL and calls
  `signIn`.
- **iOS** runs inside `ASWebAuthenticationSession`, which hands the URL back
  to the `openAuthSessionAsync` promise and emits no event. `login.tsx`
  therefore also parses the returned URL and calls `signIn` itself.

Both paths go through `useAuth().signIn` -- writing the token straight to
`expo-secure-store` is not enough, because the route guard reads the auth
context, not the store. The root layout's `(app)/_layout.tsx` enforces the
inverse -- a missing or invalid token redirects to `/login`.

The token stored on the device is also the one sent as
`Authorization: Bearer <token>` on every API call, decrypted by the backend's
`AuthMiddleware` once cookie auth is bypassed.

## Native dependencies in this build

**Every native module the app needs is installed and linked**, so a feature
does not need another rebuild to land. The list below is what the Android
build actually contains; `node scripts/check-native-linking.mjs`
verifies it against the same resolution Gradle uses.

| Package                                     | Used by                                         |
| ------------------------------------------- | ----------------------------------------------- |
| `expo-secure-store`                         | Encrypted token storage                         |
| `expo-web-browser`                          | GitHub OAuth flow                               |
| `@react-native-async-storage/async-storage` | The "onboarding seen" flag                      |
| `expo-dev-client`                           | Metro handshake, dev menu                       |
| `expo-splash-screen`                        | The launch screen (config plugin in `app.json`) |
| `react-native-svg`                          | The git graph's rail lines and commit nodes     |
| `expo-gl`                                   | The 3D dependency graph                         |
| `three` (**pinned `0.162.0`**)              | The 3D scene graph                              |
| `d3-force-3d`                               | The 3D layout force simulation                  |
| `expo-file-system`                          | Writing the export file                         |
| `expo-sharing`                              | The share sheet for exports                     |
| `expo-notifications`                        | Push on ingest completion (loaded lazily)       |
| `expo-build-properties`                     | Release-build Gradle settings (config plugin)   |

Installed but not imported anywhere yet: `expo-auth-session`,
`expo-application`, `expo-crypto`, `expo-blur`, `expo-device`, `expo-linking`,
`expo-system-ui`, `react-native-gesture-handler` and `react-native-pager-view`
(the carousel is a `FlatList`). They are listed here so the next person does
not go looking for a consumer that does not exist.

`three` is pinned to `0.162.0` because r163 dropped WebGL 1 support and
`expo-gl` provides a WebGL 1 context. Bumping it breaks the graph outright;
the pin is permanent until the renderer moves off `expo-gl`.

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
