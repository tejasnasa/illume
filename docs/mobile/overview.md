# The mobile app

Illume has a native app in [`mobile/`](../../mobile/), built with Expo SDK 57, React Native 0.86, React 19 and expo-router. It talks to the same FastAPI backend as the web client, authenticated with a bearer token instead of a cookie, and shares no code with the web client. This page covers how it relates to the web client, its toolchain, routing, sign-in and session handling, networking, every screen, push notifications, testing, and how builds are made. The 3D graph has [its own page](graph-renderer.md).

## Terms used on this page

- **Expo**: the toolkit around React Native that builds the app, manages native modules and serves the JavaScript bundle.
- **Metro**: React Native's JavaScript bundler, which a development build loads code from.
- **Development build** (or dev client): an installed app with all of Illume's native modules compiled in, which reloads JavaScript from Metro. **Expo Go**, the generic sandbox app, cannot run Illume.
- **EAS**: Expo Application Services, the cloud that builds installable APKs and store bundles.
- **Native module**: code compiled into the app binary (for example `expo-gl`). Adding one needs a new build, not a reload.

## How it relates to the web client

The web client is canonical: features are designed there and the phone follows. The two share **no code**, no workspace package and no common types module; types and design tokens are copied by hand.

| Concern       | Web ([`client/`](../frontend/overview.md))       | Mobile                                                             |
| ------------- | ------------------------------------------------ | ------------------------------------------------------------------ |
| Rendering     | React DOM, Tailwind 4                            | React Native, NativeWind 5 (`className` compiled to native styles) |
| Routing       | Next.js App Router, server components            | expo-router, client-side only                                      |
| Session       | httponly cookie                                  | `Authorization: Bearer`, token in `expo-secure-store`              |
| Data fetching | server components, server actions, browser fetch | TanStack Query over one `fetch` wrapper                            |
| Chat          | streaming agent with presets                     | the same streaming agent: `POST /chat/stream`, every preset, conversations |
| 3D graph      | `react-force-graph-3d` (WebGL 2)                 | raw `expo-gl` and three.js r162 (WebGL 1)                          |
| First screen  | marketing landing page                           | a three-screen onboarding carousel                                 |
| Look          | Geist Sans and Geist Pixel Square, pixel panels  | the same two fonts, loaded with `expo-font`, and the same palette   |
| Layout        | any viewport                                     | portrait only, dark only                                           |

Decisions behind this, recorded with the port:

- **No shared code**, so a mobile change can never trigger or break a web deploy, and because the web renders server components the phone cannot use. The cost is duplication: `mobile/src/types/` can drift from the server's models, and the palette is maintained twice (with a test keeping the two copies of the palette equal).
- **Android first.** Development happens on Windows, so the Android emulator and a physical device are the test surfaces. iOS builds come from EAS and are not exercised locally.
- **A development build, not Expo Go.** Remote push was removed from Expo Go in SDK 53, and `expo-gl` needs native code Expo Go does not have.

The chat is the web's: it streams from `POST /chat/stream`, offers every preset including the two deep agent presets, and keeps conversations. What stays web-only is the full-viewport 3D live graph, which the phone replaces with a small flat graph inside each turn (see [Chat](#chat)).

## Project layout

```text
mobile/
  app.json             Expo config: scheme "illume", icons, plugins, newArchEnabled, portrait, dark
  eas.json             build profiles and the backend URL each bakes in
  babel.config.js      babel-preset-expo only
  metro.config.js      Expo's Metro config wrapped by NativeWind
  global.css           Tailwind layers and the @theme palette
  jest.config.js       jest-expo preset, @/ mapping
  jest.setup.js        native module mocks, before the React Native environment exists
  jest.after-env.js    testing-library configuration, after it does
  __tests__/           Jest specs
  e2e/                 Maestro flows
  assets/fonts/        Geist Sans (four weights) and Geist Pixel Square, as TrueType
  scripts/             check-native-linking.mjs, generate_assets.py
  src/
    app/               expo-router routes: the file tree is the route tree
    components/        feature components: graph renderer, pickers, and folders
                       chat/, ingest/, overview/ and explorer/
    ui/                small presentational pieces: Panel, Button, Logo, PixelGraph
    hooks/             data and state hooks
    lib/               pure logic: tree building, layout maths, parsers, and
                       lib/agent/ (the stream reducer, copied from the web)
    api/               one HTTP client and one module per endpoint group
    types/             copied from the web client; may drift
    theme/tokens.ts    the palette as strings, for places className cannot reach
```

Two rules: `lib/` never imports React, so it is the easiest code to test; and `api/` never imports components, and nothing else calls `fetch`.

## Toolchain

| Package                                                | Role                                                                                          |
| ------------------------------------------------------ | --------------------------------------------------------------------------------------------- |
| `expo`, `expo-router`                                  | build tooling, native module registry, file-based routing                                     |
| `react-native` 0.86                                    | the runtime, New Architecture on                                                              |
| `nativewind` 5 (release candidate), `react-native-css` | `className` to native styles                                                                  |
| `expo-gl`                                              | a WebGL 1 context                                                                             |
| `three` **0.162.0**                                    | the 3D scene; pinned exactly, see [the graph renderer](graph-renderer.md#why-three-is-pinned) |
| `d3-force-3d`                                          | the graph layout                                                                              |
| `@tanstack/react-query`                                | server state                                                                                  |
| `expo-secure-store`                                    | the bearer token                                                                              |
| `@react-native-async-storage/async-storage`            | the onboarding flag                                                                           |
| `expo-web-browser`, `expo-auth-session`                | the OAuth browser session                                                                     |
| `expo-notifications`                                   | push, loaded lazily                                                                           |
| `expo-file-system`, `expo-sharing`                     | the `.illume` export and the share sheet                                                      |
| `react-native-svg`                                     | pixel art: starfield, thumbnails, graph sketches, the git timeline                            |
| `expo-font`                                            | loads Geist Sans and Geist Pixel Square before the first screen                               |
| `react-native-reanimated`                              | the ingest board's indeterminate bars, skeleton shimmer                                       |
| `zod`                                                  | form validation mirroring the web's schemas                                                   |

### NativeWind constraints

Styling is `className` on React Native components, compiled from `global.css`. Three constraints have each caused bugs:

1. **`className` reaches only React Native's own components.** A third-party native view such as `SafeAreaView` from `react-native-safe-area-context` ignores it, so `flex-1` on it is dropped and its children collapse to zero height. Use a plain `View` and `useSafeAreaInsets()`.
2. **No `oklch()`.** React Native's colour parser understands hex, `rgb()`, `hsl()` and names. Values handed to native APIs or three.js come from `src/theme/tokens.ts`.
3. **The palette exists twice**, in `global.css` and `tokens.ts`. `__tests__/themeSync.test.ts` parses `@theme` and fails on any value that differs.

### The `typescript` override

`package.json` overrides `typescript` to `~5.4.0`. Without it, an optional peer of `@expo/require-utils` resolves to TypeScript 7, which pulls one native binary per platform, and `npm ci` on the Linux EAS builder fails with `EBADPLATFORM`. Do not remove it.

## Running the app

```bash
cd mobile
npm install
npx expo run:android           # build and install a development build once
npx expo start --dev-client    # then serve JavaScript from Metro
```

### The backend URL

`EXPO_PUBLIC_BACKEND_URL` is inlined into the bundle at build time.

| Situation                         | Value                                                                   |
| --------------------------------- | ----------------------------------------------------------------------- |
| development, physical device      | the machine's LAN address, in `mobile/.env`                             |
| development, Android emulator     | falls back to `http://10.0.2.2:8000`, the emulator's alias for the host |
| `preview` and `production` builds | the production API, set in `eas.json`                                   |

A **release** build without a value throws at start-up with a clear message, rather than sending every request to an emulator alias.

Expo substitutes the value by matching the literal expression `process.env.EXPO_PUBLIC_BACKEND_URL` in the source. Wrapping `process.env` in a cast or destructure stops the match, and the value reads `undefined` only on an installed release build; typechecks, Jest and the bundle build all still pass. `resolveBackendUrl` in [`api/client.ts`](../../mobile/src/api/client.ts) reads it bare, and `__tests__/publicEnvInlining.test.ts` fails if that changes.

`api/ingest.ts` derives the WebSocket URL by swapping `http` for `ws`, so an HTTPS backend gives `wss://`.

## Routing

| Route                 | File                             | Shows                                               |
| --------------------- | -------------------------------- | --------------------------------------------------- |
| `/`                   | `app/index.tsx`                  | the cold-start decision, then a redirect            |
| `/onboarding`         | `app/onboarding.tsx`             | the three-screen carousel                           |
| `/login`              | `app/login.tsx`                  | GitHub sign-in, with "?" to reopen the carousel     |
| `/auth/callback`      | `app/auth/callback.tsx`          | the OAuth deep-link target on Android               |
| `/dashboard`          | `app/(app)/dashboard.tsx`        | repositories, the free-tier banner, an add button   |
| `/repo-picker`        | `app/(app)/repo-picker.tsx`      | modal route: pick a repository, then a version      |
| `/settings`           | `app/(app)/settings.tsx`         | account settings                                    |
| `/settings/ai`        | `app/(app)/settings/ai.tsx`      | the user's own AI key                               |
| `/settings/agent`     | `app/(app)/settings/agent.tsx`   | the agent's context window and default preset       |
| `/settings/mcp`       | `app/(app)/settings/mcp.tsx`     | MCP tokens and client setup                         |
| `/settings/contact`   | `app/(app)/settings/contact.tsx` | the contact form                                    |
| `/settings/delete-account` | `app/(app)/settings/delete-account.tsx` | account deletion                          |
| `/repo/[id]`          | `app/(app)/repo/[id]/index.tsx`  | the overview, or the live ingest board              |
| `/repo/[id]/glossary` | `.../glossary.tsx`               | glossary browse and search; `?letter=` opens an initial |
| `/repo/[id]/explorer` | `.../explorer.tsx`               | the file tree with a details sheet; `?file=` opens a file |
| `/repo/[id]/graph`    | `.../graph.tsx`                  | the 3D graph                                        |
| `/repo/[id]/chat`     | `.../chat.tsx`                   | streaming agent chat (hidden tab); `?q=` prefills   |
| `/repo/[id]/settings` | `.../settings.tsx`               | auto-update, export, re-ingest, delete (hidden tab) |
| anything else         | `app/+not-found.tsx`             | "This screen does not exist"                        |

```mermaid
flowchart TD
  R["/ entry"] -->|"token"| D["dashboard"]
  R -->|"no token, seen onboarding"| L["login"]
  R -->|"no token, first run"| O["onboarding"]
  O --> L
  L -->|"?"| O
  L -->|"GitHub OAuth"| C["auth callback"]
  C --> D
  D --> P["repo-picker modal"]
  D --> S["settings"]
  D --> REPO["repo id"]
  REPO --> T1["overview"]
  REPO --> T2["glossary"]
  REPO --> T3["explorer"]
  REPO --> T4["graph"]
  REPO --> H1["chat, hidden"]
  REPO --> H2["settings, hidden"]
```

- **Root layout** (`app/_layout.tsx`) is the only place providers are wired: `SafeAreaProvider`, one `QueryClientProvider`, `AuthProvider`, a `PushRegistration` that renders nothing, the status bar and a headerless `Stack` with a transparent scene background over a still pixel `Starfield`. It also loads the fonts with `useFonts` and shows the splash until they are ready. It also bridges app foreground to React Query's focus refetch and exports an `ErrorBoundary` with "Try again".
- **Entry decision** (`app/index.tsx`): with a token, go to the dashboard without reading the onboarding flag; without one, onboarding on a first run, otherwise login. It shows a spinner rather than nothing, because some Android builds have already dismissed the splash.
- **Auth gate** (`app/(app)/_layout.tsx`): a splash while loading, a `<Redirect>` to login without a token. Ownership is the backend's job; it returns 404 for another user's repository.
- **Repository shell** (`app/(app)/repo/[id]/_layout.tsx`): a `Tabs` navigator with a custom top tab bar matching the web navbar. Chat and settings are registered with `href: null` and filtered from the bar, but navigable by URL. A repository that is not ready shows only Home. A deep link to a tab of an unready repository navigates (not replaces) back to the overview, because replacing a tab with a tab leaves two routes of the same name.
- **Search params.** Screens nested under `repo/[id]/` must use `useGlobalSearchParams()`. `useLocalSearchParams()` returns only the current route's own params, so it gave `undefined` for `id`, every query stayed disabled, and three tabs loaded forever. Each call site carries a comment so it is not "simplified" back.
- **Two kinds of modal.** `/repo-picker` is a modal route with its own URL; the explorer's file sheet is a modal component, because it is a detail of the current screen.

## Sign-in and the session

The backend issues the same JWT as for the web. The phone stores it in `expo-secure-store` and sends it as a bearer token. A token issued to an allowlisted deep link (or to a request carrying `X-Illume-Client: mobile`) gets the longer `MOBILE_TOKEN_EXPIRE_MINUTES` lifetime, 90 days by default.

```mermaid
sequenceDiagram
  participant App as App login
  participant Br as System browser
  participant API as FastAPI
  participant GH as GitHub
  App->>Br: openAuthSessionAsync to the GitHub login route
  Br->>API: GET auth github with the app callback as state
  API->>GH: consent redirect
  GH->>API: callback with code and state
  API->>API: exchange code, link user, mint JWT
  alt callback is on OAUTH_REDIRECT_ALLOWLIST
    API-->>Br: redirect to the app callback with the token
    Br-->>App: deep link on Android, session result on iOS
    App->>App: signIn stores token and sets context
  else not allowlisted
    API-->>Br: redirect to FRONTEND_URL
  end
```

- **Two return paths.** Android delivers the redirect as a deep link that mounts `app/auth/callback.tsx`. iOS returns it to the `openAuthSessionAsync` promise and emits no event, so `login.tsx` parses `result.url` itself. Both call the same `signIn`.
- **`signIn` writes the store and the context.** The route guard reads the auth context; an early version wrote only SecureStore and the guard sent the user back to login. `signIn` stores the token, validates it with `GET /auth/me`, sets `{ token, user }`, and returns false only when the backend rejects it.
- **Rejected versus unreachable.** On a cold start `fetchMe` classifies the result: `ok` adopts the token; `rejected` (401 or 403) clears it; `unreachable` (5xx, DNS, timeout) **keeps** it and retries once immediately and again on every foreground, so losing signal never signs a user out. Before clearing, the store is re-read, in case a deep-link sign-in wrote a fresh token meanwhile.
- **Expiry.** Any 401 calls a sign-out handler, debounced for two seconds because one screen can fire several failing queries. A 403 does not sign out.
- **Sign-out** deregisters the push token (errors ignored), clears SecureStore and the context, and clears the whole query cache, because query keys carry no user id.
- The backend's `OAUTH_REDIRECT_ALLOWLIST` must contain `illume://auth/callback` exactly; see [environment variables](../reference/environment.md).

## Networking

Every request goes through `apiRequest` in [`api/client.ts`](../../mobile/src/api/client.ts):

- resolves the base URL and reads the token on every call (cheap after the first read);
- sets `Accept: application/json`, `Content-Type` only with a body, `Authorization` only with a token;
- parses 204 and empty bodies to `undefined` and non-JSON bodies as text;
- throws `ApiError` on any non-2xx, with a `kind` of `unauthorized`, `notFound`, `quota`, `clientError`, `server`, `network` or `unknown`. `quota` (402) is treated specially: the remedy is the user's own key, not a retry.

Every API function takes an options bag with `backendUrl` and `fetchImpl`, so tests inject transport instead of mocking modules.

| Module          | Calls                                                                                   | Keyed by              |
| --------------- | --------------------------------------------------------------------------------------- | --------------------- |
| `repository.ts` | list, get, create (202)                                                                 | `repo_number` for get |
| `graph.ts`      | `GET /graph?level=`                                                                     | UUID                  |
| `explorer.ts`   | the file graph's nodes, and one file's symbols and recent commits (`/file?path=&commits=3`) | UUID              |
| `guide.ts`      | the onboarding guide, the stats and the recent activity                                 | UUID                  |
| `glossary.ts`   | browse (optionally by initial, `#` for the rest) and search                             | UUID                  |
| `ownership.ts`  | ownership (optionally one file) and knowledge silos                                     | UUID                  |
| `agentStream.ts` | `POST /chat/stream`, read as server-sent events through `expo/fetch`                   | UUID                  |
| `conversations.ts` | list, get, rename and delete conversations and turns                                 | UUID                  |
| `chat.ts`       | the Classic `POST /chat`, history, delete one, clear; no longer used by the chat screen | UUID                  |
| `account.ts`    | agent defaults, MCP tokens and account deletion                                         | user                  |
| `settings.ts`   | AI credentials, auto-update, sync now, re-ingest, delete, the `.illume` export, contact | user or UUID          |
| `push.ts`       | register, deregister and status of the push token                                       | user                  |
| `ingest.ts`     | the ingest WebSocket URL, with `?token=`                                                | UUID                  |
| `github.ts`     | the GitHub proxy: repositories (with a server-side `q` name search), branches, commits  | user                  |

**The identifier split causes most 404s.** List and detail routes use `repo_number`; everything else uses the UUID. A wrong id reads like "no glossary yet", so screens resolve the number to the record first and use `repo.id` after.

### Server state

One `QueryClient` with `retry: 1` and `staleTime: 30_000`. Keys come from one factory, `api/queryKeys.ts`, all starting with a domain (`["repositories", ...]` or `["github", ...]`), so one call can invalidate every repository-scoped entry.

| Mutation                        | Invalidated                    |
| ------------------------------- | ------------------------------ |
| create repository               | the list                       |
| chat send, delete, clear        | that repository's chat history |
| auto-update change, sync queued | the list and the detail        |
| re-ingest                       | every repository key           |
| delete repository               | every repository key, removed  |
| sign-out                        | the whole cache                |

Invalidating only the list after a re-ingest once left a cached detail saying `ready`, sending the user to the stale overview instead of the ingest board.

Two pollers: the dashboard refetches every 5 s while any repository is neither ready nor failed, and `RepoStatusPoller` invalidates the detail every 5 s (`POLL_INTERVAL_MS`) while an ingest or sync is in progress, giving up after 65 minutes (`MAX_POLL_MS`), five minutes past the worker's 60-minute sync lease, because a killed sync cannot clear its own status.

## Screens

- **Onboarding and sign-in.** A pixel constellation (`ui/PixelGraph`, drawn with react-native-svg and stepped every 100 ms) sits behind the carousel and the login screen, and stands still when the system's reduce-motion setting is on.
- **Dashboard.** A `> illume ls_` header, a count line, a search box and status filter chips (`lib/repoFilter.ts`); three skeleton cards while loading; an error panel with retry; an empty state; otherwise repository cards with a still pixel thumbnail of the repository's own graph (`ui/RepoThumb`, from `GET /graph/thumbnail`, with a seeded placeholder when there is none), pull-to-refresh, a floating add button, and Settings and Log out in the header. Settings is in the header because the free-tier banner, which used to link there, hides itself for users with their own key.
- **Repository picker.** Step one lists the user's GitHub repositories (100 per page) or accepts a pasted URL. The search box is sent to the server as `q` after a 400 ms pause, so it reaches repositories beyond the pages already loaded; the term is part of the query key, so each term keeps its own pages. Step two is a commit timeline (`GitGraph`, SVG) for choosing a branch or commit. It has an explicit Cancel, because a modal route has no visible dismissal on iOS. Creating a repository refreshes the profile, since the free-tier counter changed.
- **Overview.** `IngestFlow` while ingesting; when ready, a stack of cards in the web's order (`ui/RepoDetail`, `components/overview/OverviewCards`): status, branch and commit, the title, the risk spread, a button into chat, the architecture brief, a flat graph tile, at a glance with a language bar, start here (the first reading-order files), riskiest to change, recent activity, tech stack and who to ask. Each card is left out when its data is missing. The guide, stats, activity and file graph are fetched only when the repository is ready; the file graph uses the graph screen's query key, so it is downloaded once for the overview, the explorer, the chat and the graph. The graph tile and risk spread are computed from that payload (`lib/overview.ts`).
- **Glossary.** Server-side search debounced by 400 ms, page size 20, previous data kept while paging so the list does not blank. An A to Z rail (`components/GlossaryLetters`) puts each initial on its own small card; initials with no terms are dimmed, `#` collects names that start with anything else, and picking one leaves search because the two filters are different routes. Three different empty messages: the repository failed to load, nothing matched, or there is no glossary.
- **Explorer.** A tree built client-side from the file-level graph by `lib/fileTree.ts`: build a nested tree (a path that is both a file and a directory keeps the directory), flatten against the expanded set, sort directories first. Rendered by a `FlatList`, so re-renders follow visible rows. Tapping a file, or arriving with `?file=`, opens a sheet with the file's details: its reading-order note, ask and graph actions, a still neighbourhood picture (importers left, imports right, `lib/neighbourhood.ts`), its symbols and its three latest commits from `GET /file`, who owns it, and the files that import it and that it imports. Tapping a neighbour moves the selection to it.
- **Graph.** See [the graph renderer](graph-renderer.md).
- **Chat.** The web's streaming agent. `api/agentStream.ts` reads `POST /chat/stream` through `expo/fetch` (React Native's own `fetch` does not expose a streaming body), a server-sent events parser feeds a reducer copied from the web's `lib/agent/`, and the screen renders the run as it arrives. The preset picker offers Auto, Classic, Hybrid, Hybrid + rerank, Structural and the two deep agent presets (`deep_agent`, `deep_agent_workers`); on the free tier Auto and the agent presets are disabled with a reason, and the choice is remembered per repository in AsyncStorage. An advanced sheet tunes the preset's overrides. Each turn shows an activity block (planner steps, sub-questions numbered by worker, tool calls and retrievals), the answer with tappable citation chips, a stale notice when the snapshot has moved, and the run's cost. Conversations are listed and switched in a sheet. Below the activity, a collapsed graph panel (`components/chat/RunGraph`) draws a flat sketch of the file graph with the files the run touched lit in the colour of the lane that touched them, and, once finished, the files the answer cites in gold; a turn restored from the server has no record of touched files, so it shows the cited ones only. A `?q=` parameter prefills the composer, which is how the explorer and graph inspector ask about a file. The composer is disabled when the free allowance is spent, and is not drawn until the repository record resolves, which once let a fast tap post to `/api/v1/repository//chat`.
- **Settings.** Account-level: AI credentials, agent defaults, MCP tokens, contact, about, account deletion and log out. Repository settings live behind the gear in the repository header: auto-update and sync, export, re-ingest and delete.

### The live ingest board

`useIngestStream` owns the WebSocket and normalises frames, like the web hook. `IngestFlow` folds them into stage states with the same rules as the web (see [the WebSocket page](../interfaces/websockets.md#from-frames-to-node-states)): a headline that moves from queued through each stage to "Still working…" after five minutes of silence; a refresh 900 ms after completion or 2500 ms after failure, once each; one reconnect after a 15-second grace when the socket closes early. `PipelineBoard` draws the web's seven columns (Fetch, Read, Connect, Score, Write, Index, Done) as stacked stage cards, each with a state mark, a meta line (`1,200 / 4,000 files`, `2,871 dependencies`) and a bar that fills from the frame counters or sweeps while a stage runs without one; the sweep stops when the system's reduce-motion setting is on. `IngestLog` is the raw frame log, which follows the tail only while the reader is at the tail. The board's wording lives in `lib/pipelineBoard.ts` and the frame folding in `lib/ingestFlow.ts`; the cards are drawn from the state map alone, so nothing advances without a frame. After the first successful ingest, and never at launch, the app asks for notification permission.

### Export

`ExportIllumeButton` fetches the [`.illume` export](../interfaces/illume-export.md), writes it to the cache directory as `<name>.illume` (the name from the file's `repo=` line, sanitised to `[a-zA-Z0-9._-]`), and opens the share sheet. The cache file is not deleted, since the share target may still be reading it.

### Push notifications

- The token **re-registers on every launch** from the root layout, because Expo rotates tokens.
- The server's payload carries `event`, `repository_id`, `repository_number` and `repository_name`; `notificationPath` builds `/(app)/repo/{repository_number}` from it.
- `expo-notifications` is required lazily, so a build without push still loads.
- A release build needs `google-services.json` and `android.googleServicesFile` in `app.json`; without them registration silently never happens. The server side is [`api/v1/push.py`](../../server/app/api/v1/push.py) and the `push_tokens` table.

## Visual system

- The palette is sRGB hex or `rgba()`, defined in `global.css` and `tokens.ts` and kept equal by a test, and follows the web's: card `#0e0e11`, accent `#f6339a`, plus the `warning`, `selected`, `match`, `subtle-foreground`, `faint-foreground` and `border-strong` tokens.
- **Fonts.** Geist Sans (Regular, Medium, SemiBold, Bold) and Geist Pixel Square are bundled in `assets/fonts/` as TrueType, because React Native cannot load the web's WOFF2. They are loaded by `useFonts` in the root layout, and `font-sans*` and `font-pixel` in `global.css` name the same family strings. React Native picks a weight by family name, so each weight is its own entry in `lib/fonts.ts`.
- **Panels** (`ui/Panel`) are a thin border, the flat card fill and a small radius, with an uppercase pixel `Eyebrow` for titles. The starfield and every thumbnail are drawn with react-native-svg; there is no Skia.
- Touch targets are at least 44 points. Portrait and dark only.
- Screens apply `paddingTop: insets.top` on a plain `View`. The chat pads by the keyboard height from `useKeyboardHeight` plus the bottom inset, because `KeyboardAvoidingView` misjudges the keyboard on Android with edge-to-edge display.

## Testing

```bash
npm test           # Jest through jest-expo
npm run typecheck  # tsc --noEmit
```

| Area       | Examples                                                                                   |
| ---------- | ------------------------------------------------------------------------------------------ |
| pure logic | `graphLayout`, `graphSelection`, `graphBrackets`, `fileTree`, `overview`, `neighbourhood`, `pipelineBoard`, `agentLib` |
| hooks      | `useAuth`, `useChat`, `useIngestStream`, `useRepoForm`, `useRepositories`, `useAutoUpdate` |
| screens    | dashboard, chat (scripted stream), glossary, explorer, graph, ingest board, overview, settings, onboarding |
| contracts  | `themeSync`, `routes` (every route module loads), push payload keys, `publicEnvInlining`   |

- `jest.setup.js` mocks native modules and runs **before** the React Native environment exists; anything needing `react-native` goes in `jest.after-env.js`, which also raises the `waitFor` timeout to 5 s for full parallel runs.
- Storage is injected through `__setTokenStoreImplementation` and `__setOnboardingFlagImplementation`, which production code never calls.
- The GL path is not tested in Jest (there is no GL context); the layout and camera maths it depends on are.
- `e2e/` holds Maestro flows for onboarding, the dashboard, the repository shell and chat. They need a device, a reachable backend and an account signed in by hand, because Maestro cannot drive the GitHub OAuth round trip.
- There is no linter configured for `mobile/`.

## Building and releasing

| EAS profile   | Produces                                  | Backend                      |
| ------------- | ----------------------------------------- | ---------------------------- |
| `development` | a development build                       | from `mobile/.env` via Metro |
| `preview`     | an installable APK, internal distribution | production API               |
| `production`  | a store build                             | production API               |

```bash
npx eas login
npx eas build --profile preview --platform android
```

- `eas-cli` is a dev dependency, so `npx eas` runs the right binary; outside `mobile/` an unrelated `eas` package is resolved instead.
- **EAS archives the git repository root**, so `mobile/.easignore` rules are matched at any depth. A rule saved with a CRLF line ending matches nothing and the whole `node_modules` tree is uploaded (about 1.6 GB); `.gitattributes` pins the file to LF.
- Adding a native module needs a new build; the symptom of forgetting is a `ViewManager` error naming the missing component. `node scripts/check-native-linking.mjs` compares declared modules against what Gradle resolves.
- `appVersionSource: "remote"` lets EAS own the Android `versionCode`.
- The web client serves an Android download page at `/mobile`.

## Troubleshooting

| Symptom                                                                             | Cause and fix                                                                            |
| ----------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| every request fails with a network error on a device                                | the backend URL is missing or `localhost`; set a reachable host                          |
| release build says `EXPO_PUBLIC_BACKEND_URL is not set` although `eas.json` sets it | the read was wrapped, so Expo did not substitute it; keep it a literal member expression |
| sign-in finishes in the browser but the app stays on login                          | the callback is not on `OAUTH_REDIRECT_ALLOWLIST`, or the context was not updated        |
| a screen shows only its header                                                      | `useLocalSearchParams` under a dynamic segment; use `useGlobalSearchParams`              |
| `Can't find ViewManager ...`                                                        | a native module is missing from the installed build; rebuild                             |
| blank graph, no error                                                               | `gl.endFrameEXP()` not called; see [the graph renderer](graph-renderer.md)               |
| `WebGL 1 is not supported since r163`                                               | `three` was upgraded; restore the exact pin                                              |
| content under the keyboard                                                          | `KeyboardAvoidingView` with edge-to-edge; pad by `useKeyboardHeight()`                   |
| one card a different shade                                                          | `global.css` and `tokens.ts` drifted; `npm test` names the token                         |
| EAS upload takes gigabytes                                                          | `.easignore` has CRLF line endings                                                       |

## Design trade-offs and limits

- **Duplication over coupling.** Two independent apps, at the cost of copied types and a twice-maintained palette.
- **Feature lag.** The live graph behind the chat is a flat sketch in each turn rather than a full-viewport 3D view, and the run replay is the cited files only.
- **Chat streaming is unverified off a device.** It needs `expo/fetch` to deliver a streaming body, which Jest cannot show; there is no non-streaming fallback.
- **iOS is unverified locally.**
- **Push needs Firebase configuration** that is not in the repository.
- **The overview, explorer and chat download the whole file graph**, once, for the tree, the neighbours, the risk spread and the run graph.
- **The backend URL is baked in.** Changing it is a new build.
- **No offline mode.** The only tolerance is keeping a session whose profile could not be read.
- **Token in the WebSocket URL**, as on the web.

## Related documentation

- [The mobile graph renderer](graph-renderer.md): the 3D view in depth.
- [The web client](../frontend/overview.md): the canonical client.
- [API reference](../api.md): every endpoint the app calls.
- [The ingest WebSocket](../interfaces/websockets.md): the frames the ingest board renders.
- [Authentication](../security/auth.md): the JWT, the bearer branch and the OAuth callback.
