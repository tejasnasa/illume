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

The dev build links these native modules so later milestones do not require a
rebuild until `app.json` changes:

| Package                                     | Used by                                         |
| ------------------------------------------- | ----------------------------------------------- |
| `expo-secure-store`                         | Encrypted token storage                         |
| `expo-auth-session` + `expo-web-browser`    | GitHub OAuth flow                               |
| `expo-application` + `expo-crypto`          | OAuth state params (transitive of auth-session) |
| `@react-native-async-storage/async-storage` | Non-secret prefs                                |
| `expo-dev-client`                           | Metro handshake, dev menu                       |

Future milestones add `expo-gl`, `three`, `expo-notifications`, `expo-blur`,
etc. on demand -- those will require a rebuild at the time they're added.
