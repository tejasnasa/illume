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
    ├── hooks/              ports of client/src/hooks/
    ├── api/                one client, token-injecting
    ├── types/              copied from client/src/types/
    ├── graph/              the 3D renderer (renderer milestone)
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

## Deep links

The `illume` URL scheme is registered in `app.json`. Phase 2 wires OAuth's
return path to `illume://auth/callback`.

## Native dependencies in this build

The dev build links these native modules so subsequent phases do not require a
rebuild until `app.json` changes:

| Package                                     | Used by                                                  |
| ------------------------------------------- | -------------------------------------------------------- |
| `expo-secure-store`                         | Encrypted token storage (Phase 2)                        |
| `expo-auth-session` + `expo-web-browser`    | GitHub OAuth flow (Phase 2)                              |
| `expo-application` + `expo-crypto`          | OAuth state params (Phase 2, transitive of auth-session) |
| `@react-native-async-storage/async-storage` | Non-secret prefs (Phase 4+)                              |
| `expo-dev-client`                           | Metro handshake, dev menu                                |

Future phases add `expo-gl`, `three`, `expo-notifications`, `expo-blur`, etc.
on demand — those will require a rebuild at the time they're added.
