# Rendering the graph

The web client draws the dependency graph in two quite different ways. The graph page uses a real 3D force-directed layout in WebGL ([`GraphClient.tsx`](../../client/src/components/GraphClient.tsx)), with search, a level switch, a reading-order tour and an inspector. Everywhere else (the background of every repository page, the live chat graph, repository cards, file neighbourhoods and the marketing pages) uses a hand-written pixel-art constellation on a 2D canvas ([`PixelGraph.tsx`](../../client/src/components/PixelGraph.tsx) and [`lib/pixelGraph.ts`](../../client/src/lib/pixelGraph.ts)). This page covers both renderers, every component built on them, and the 2D commit timeline that is often confused with them.

## Terms used on this page

- **Force-directed layout**: positions computed by simulating nodes that repel each other and links that pull like springs, so connected files end up near each other.
- **WebGL**: the browser's GPU drawing API. Three.js and `react-force-graph-3d` sit on top of it.
- **Constellation**: Illume's name for the pixel renderer's picture: directory "hubs" with files clustered round them, projected from 3D onto a coarse pixel grid.
- **Cell**: the size, in device pixels, of one pixel of the constellation. The default is 4.

## Which component is which

| Component                                                                     | Renderer        | Interactive               | Data                                   | Used in                                                |
| ----------------------------------------------------------------------------- | --------------- | ------------------------- | -------------------------------------- | ------------------------------------------------------ |
| [`GraphClient`](../../client/src/components/GraphClient.tsx)                  | 3D WebGL        | yes                       | `GET /graph?level=file\|symbol`, guide | `app/repo/[id]/graph/page.tsx` only                    |
| [`BackgroundGraph`](../../client/src/components/BackgroundGraph.tsx)          | pixel           | no                        | the layout's file graph                | `app/repo/[id]/layout.tsx`, through `RepoGraphContext` |
| [`LiveGraph`](../../client/src/components/chat/LiveGraph.tsx)                 | pixel           | no                        | the layout's file graph, agent events  | the chat page, on wide screens                         |
| [`NeighbourhoodGraph`](../../client/src/components/ui/NeighbourhoodGraph.tsx) | pixel           | no                        | one file, its importers and imports    | `FileDetailCard` in the explorer                       |
| [`RepoThumb`](../../client/src/components/ui/RepoThumb.tsx)                   | pixel, still    | no                        | `GET /graph/thumbnail`                 | `RepoCard` on the dashboard                            |
| [`OverviewGraphTiles`](../../client/src/components/OverviewGraphTiles.tsx)    | HTML and SVG    | links only                | the layout's file graph                | the repository overview, `app/repo/[id]/page.tsx`      |
| [`GitGraph`](../../client/src/components/GitGraph.tsx)                        | 2D SVG timeline | yes                       | GitHub branches and commits            | `RepoPickerModal`, `RepoSettings`                      |
| `PixelGraph` with `source="hero"` or `"sample"`                               | pixel           | cursor and drag, per page | generated scenes                       | landing, login, contact and mobile pages, `IngestFlow` |

`GitGraph` is **not** a dependency graph: it draws branch lanes and commits so the user can pick a branch and commit to ingest. It is listed here only because its name invites the confusion.

## The 3D graph page

`app/repo/[id]/graph/page.tsx` is a server component. It loads the repository (`GetRepository`), the graph at the requested level (`getRepoGraph(repo.id, level)`, defaulting to `file`) and the onboarding guide (`GetGuide`), and hands all three to `GraphClient`.

`react-force-graph-3d` is imported with `next/dynamic` and `{ ssr: false }`, because Three.js needs browser globals that do not exist during server rendering. Any new WebGL component must follow the same pattern.

### Visual mapping

| Property        | Rule                                                                                                                   |
| --------------- | ---------------------------------------------------------------------------------------------------------------------- |
| node size       | `nodeValue = Math.sqrt(loc \|\| 10) * 0.5`, with `nodeRelSize` 4, so a file without LOC is drawn as if it had 10 lines |
| node colour     | search match `#a855f7`, else selected `#0078ff`, else critical `#ef4444`, caution `#facc15`, anything else `#22c55e`   |
| node detail     | `nodeResolution` 12 segments per sphere, `nodeOpacity` 0.9                                                             |
| link colour     | `rgba(0,120,255,0.7)` and width 2 when incident to the selected node, else `rgba(255,255,255,0.3)`                     |
| link particles  | one directional particle per link, speed 0.005                                                                         |
| highlight frame | a corner-bracket sprite in `#f6339a` round the selected node, and one in the match colour round every search match     |

The match colour is checked **before** the selection colour, so a selected node that also matches the search is purple. Because unscored files are labelled `medium` by the server, they fall through to green, the same as `safe`.

The brackets are `THREE.Sprite`s with a canvas texture drawn once per colour by `getBracketTexture` and shared. The texture uses `NearestFilter`, so the corners stay crisp pixels at any distance, and `depthTest` is off, so a bracket is never hidden behind another node. One `requestAnimationFrame` loop resizes every live bracket each frame. A bracket's base size follows its node's size, but it is never drawn smaller than `BRACKET_MIN_PX = 28` screen pixels: the loop converts that to world units from the camera's distance to its target, its field of view and the canvas height, so zooming out keeps the brackets readable instead of shrinking them to dots. The selected node's bracket also "breathes" with a stepped pulse (`Math.round(Math.sin(now / 333))`, so it jumps between three sizes, ±6 %, rather than scaling smoothly). Brackets whose node has left the scene are dropped from the loop.

Selection is the only focus mechanism. Neighbours are not dimmed or recoloured; only the links touching the selected node change colour and width.

### Controls

- **Search.** Case-insensitive substring match on each node's `label` or `path`. The count of matches is shown; matching nodes turn purple and get brackets. Changing the query calls the graph's `refresh()` so node objects (and their brackets) are rebuilt.
- **Level switch.** "Files" and "Symbols" buttons call `router.push('/repo/{id}/graph?level=...')`. A veil covers the graph until the new data arrives, so the old layout is not shown with the new level's label.
- **Inspector.** Clicking a node opens `GraphCard` with its details and its importer and import lists, computed from the loaded links. Choosing an entry there selects that node.
- **Legend.** The colour key for the criticality labels, the selection and search colours.

### The reading-order tour

The tour walks the [reading order](../pipeline/generation.md#the-reading-order) file by file.

1. The guide's `reading_order` entries are sorted by `position` and joined onto graph nodes **by `path`**, because the guide endpoint does not return node ids or tiers. Entries whose path is not in the current graph are skipped, so at symbol level, where nodes are functions, the tour has nothing to show.
2. "Play tour" selects the first file, then advances every `TOUR_STEP_MS = 4000` ms, wrapping round at the end. Previous and next buttons move one step and also wrap.
3. The panel shows the entry's annotation. Selecting any node by clicking it syncs the tour to that node's position if it is in the order; clearing the selection stops the tour.
4. With no guide the tour panel is hidden rather than disabled.

### Performance

There is no node cap on the server, and `GraphClient` draws every node it receives. The guards are a low sphere resolution, one particle per link and shared bracket textures. A repository with thousands of files is drawable but slow on modest hardware; the symbol level is several times larger again.

## The pixel constellation

`PixelGraph` is a single `<canvas>` with no WebGL. Every frame it projects a small 3D scene onto a grid of cells and draws it with `fillRect`.

### Building a scene

[`lib/pixelGraph.ts`](../../client/src/lib/pixelGraph.ts) turns a `Graph` into a `PixelScene`:

| Function                    | What it builds                                                                 |
| --------------------------- | ------------------------------------------------------------------------------ |
| `sceneFromGraph(graph, 23)` | the real repository: one hub per directory group, files placed round their hub |
| `heroScene()`               | the generated constellation on the landing page                                |
| `sampleScene()`             | a smaller generated scene for places with no repository                        |
| `buildScene`                | the shared placement used by all three                                         |

`sceneFromGraph` rules, with the constants from that file:

- More than `MAX_FILES = 2000` files: keep the 2000 with the highest fan-in.
- Group by directory. More than `MAX_GROUPS = 9` groups: keep the largest eight and fold the rest into one `other/` group.
- At most `MAX_LINKS = 3000` links are kept.
- `groupDepth` gives each group a depth between 1 and 5 so hubs sit at different distances from the camera within `DEPTH = 3.2`.
- Nodes shrink by ×0.8 above 150 files and ×0.6 above 400, so a big repository does not become one blob.
- Positions come from `mulberry`, a seeded random generator, so the same repository always produces the same picture. The default seed is 23.

### Drawing a frame

`drawFrame(canvas, off, scene, frame)`:

1. Sizes a scratch canvas to the visible canvas divided by the cell size, and draws everything there at low resolution.
2. Paints a soft cyan "light pool" round the cursor or light position, `lightRadius` (0.3) of the smaller dimension.
3. Rotates every node by the camera's yaw and pitch and projects it, spread across `spreadX` (0.36) and `spreadY` (0.4) of the canvas.
4. Draws links, batched by tint and by one of `ALPHA_STEPS = 6` opacity steps, so there are a few dozen stroke calls rather than one per link.
5. Draws particles along followed links, then nodes as squares, then any labels.
6. Scales the scratch canvas up to the visible one with smoothing off, which is what makes it look like pixel art.

An optional `reveal` draws only the first fraction of files, which is how `IngestFlow` grows the constellation as an ingest parses files. A directory hub appears with its first file.

### Component props

| Prop           | Default | Effect                                                                     |
| -------------- | ------- | -------------------------------------------------------------------------- |
| `source`       |         | a `Graph`, or `"hero"` or `"sample"` for generated scenes                  |
| `followCursor` |         | the camera turns toward the cursor and the light follows it                |
| `spin`         |         | slow automatic rotation                                                    |
| `draggable`    |         | drag to rotate, at `DRAG_RADIANS_PER_PX = 0.008`, pitch limited to ±0.9    |
| `still`        |         | draws one frame at yaw 0.7, pitch 0.3 and time 4000 ms, then stops         |
| `cell`         | 4       | device pixels per constellation pixel                                      |
| `hubLabels`    |         | names the directory hubs                                                   |
| `focusLabel`   |         | names the node nearest the focus                                           |
| `turnTo`       |         | a path to turn the camera to face (eased at `CAMERA_EASE = 0.06`)          |
| `reveal`       |         | the fraction of files to draw                                              |
| `decorate`     |         | a per-frame callback that returns styles, followed links and a pinned node |

After the cursor leaves, the camera holds its pose for `CURSOR_HOLD_MS = 3500` before drifting.

Costs are kept low by:

- capping `devicePixelRatio` at 2;
- pausing the animation loop when an `IntersectionObserver` reports the canvas off screen;
- honouring `prefers-reduced-motion` by drawing a still frame;
- reading `decorate` from a ref each frame, so a caller that changes highlights ten times a second does not re-render React or rebuild the scene.

### The background graph

The repository layout (`app/repo/[id]/layout.tsx`) fetches the file graph once with `getRepoGraph(repo.id, "file")` and puts it in `RepoGraphProvider` ([`RepoGraphContext.tsx`](../../client/src/components/RepoGraphContext.tsx)), so every repository page shares one fetch. `BackgroundGraph` draws it behind the page with `focusLabel={false}`, and renders nothing when the graph is missing or empty.

- On the graph and settings routes (`isVeiledPath`) the background is **veiled**: covered with a blurred, 70 % background-colour layer, so it does not compete with the 3D graph or a form.
- On the chat route (`isChatPath`) the background steps aside, because `LiveGraph` draws the same graph in the foreground.

### The live chat graph

`LiveGraph` follows an agent run (see [the agent](../retrieval/agent.md#events)). It takes no pointer input. From the agent reducer's highlights it:

- colours each file a tool call touched in the colour of the lane (main agent or planner worker) that touched it, using the palette in `lib/agent/palette.ts`;
- glows the files the current call is looking at (`CURRENT_COLOR`) and marks cited files (`CITED_COLOR`);
- runs a particle along each of the last `FOLLOWED_EDGES = 6` moves between files;
- turns to face the file a tool call lands on, boxed and named.

All of that is passed through `decorate`, so the canvas never re-renders. The chat page imports `LiveGraph` dynamically with `ssr: false` and only shows it on wide screens with a non-empty graph, so a phone never downloads it.

### File neighbourhoods

In the explorer, `FileDetailCard` shows `NeighbourhoodGraph`: a constellation of the selected file, the files importing it and the files it imports, built client-side by `neighbourhood()`. Every node is given `criticality_score: 50`, the selected file is tinted accent pink (`246,51,154`), and the camera turns to face it. The graph is memoised on the ids, so a parent passing new but equal arrays does not restart the animation.

### Repository card thumbnails

`RepoThumb` draws a 360 × 128 still frame. For a ready repository it fetches `GET /api/v1/repository/{id}/graph/thumbnail` (the 120 busiest files; see [the dependency graph](dependency-graph.md#get-graphthumbnail)). For a repository still ingesting, failed, or with a fetch error or no files, it draws a seeded placeholder: a `mulberry32` generator seeded by a hash of the repository id, so each card's placeholder is stable across visits.

### Overview tiles

`OverviewGraphTiles` on the repository overview reads the shared graph and shows:

- `RiskSpread`: how many files are critical, caution or safe, linking to the graph page. Anything other than `critical` or `caution` counts as safe, matching the 3D colours.
- `GraphTile`: a flat map of the graph.

Both render nothing until the layout has the graph, so a failed fetch hides the tiles rather than showing zeros.

## The commit timeline

`GitGraph` draws the branches and commits of a GitHub repository as lanes, using `useGitGraph` to load them. Lanes are coloured from a six-colour palette in allocation order, the first lane being the mainline. Clicking a commit calls `onSelect(branch, sha)`, which is how the repository picker and the settings page choose what to ingest. It draws no dependency data.

## Design trade-offs and limits

- **Two renderers.** WebGL gives the graph page real 3D layout and picking; the pixel canvas is cheap enough to run behind every page and on a phone-sized screen, and matches the product's pixel style. The cost is two code paths that draw the same data differently.
- **No server-side cap for the 3D page.** Very large repositories are slow to lay out and draw. The pixel renderer caps itself at 2000 files and 3000 links, choosing by fan-in.
- **Selection does not dim the rest.** Only incident links change, which is easy to miss in a dense graph.
- **The tour needs file level.** At symbol level the reading order has no matching nodes.
- **The constellation is not a layout.** Files are placed round their directory hub, not by their links, so it shows structure by folder, not by dependency.
- **Mixed-case criticality.** The tiles normalise case and the 3D page compares exact strings, so a mixed-case value would be counted and coloured differently. The scorer only writes lower case.

## Related documentation

- [The dependency graph](dependency-graph.md): the payloads these components draw.
- [The mobile graph renderer](../mobile/graph-renderer.md): the same constellation on a phone.
- [Frontend overview](../frontend/overview.md): routing, data fetching and the shared repository layout.
- [The agent](../retrieval/agent.md): the events `LiveGraph` follows.
