# The mobile graph renderer

The mobile app draws the dependency graph in 3D with three.js on a raw `expo-gl` context, with no React 3D library and no reconciler in the draw path. The layout is computed on the phone with `d3-force-3d`, in chunks the user can watch and abandon; the scene is built once imperatively and one animation loop owns the camera and the draw. This page explains the layout, the renderer, picking and gestures, the controls, the constraints that pin the stack, and the failure modes that produce a blank screen without an error.

## Terms used on this page

- **`expo-gl`**: Expo's module that gives a React Native view (`GLView`) a WebGL 1 rendering context.
- **Instanced mesh**: one draw call that renders many copies of the same geometry with a per-copy transform and colour, used here for all nodes.
- **Force simulation**: the layout algorithm. Nodes repel, links pull, and repeated "ticks" move positions toward equilibrium.
- **Bounding radius**: the radius of the sphere enclosing the laid-out graph, which most sizes and distances are expressed as a fraction of.

## The three layers

```mermaid
flowchart LR
  G["Graph payload<br/>nodes and links"] --> L["computeLayout<br/>d3-force-3d, chunked"]
  L --> P["positions, indexed links,<br/>bounding radius"]
  P --> R["GraphRenderer<br/>expo-gl and three"]
  R --> C["camera, haloes, picking"]
```

| File                                                                                | Role                                                           |
| ----------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| [`lib/graphLayout.ts`](../../mobile/src/lib/graphLayout.ts)                         | `computeLayout`, `defaultTicks`, `boundingRadius`              |
| [`components/GraphRenderer.tsx`](../../mobile/src/components/GraphRenderer.tsx)     | scene construction, the frame loop, gestures and picking       |
| [`lib/graphCamera.ts`](../../mobile/src/lib/graphCamera.ts)                         | pure orbit-camera maths: `orbitAt`, `clampPhi`, `projectPoint` |
| [`lib/graphSelection.ts`](../../mobile/src/lib/graphSelection.ts)                   | search matching, incident links, the reading-order tour steps  |
| [`lib/graphTypes.ts`](../../mobile/src/lib/graphTypes.ts)                           | node colours and `criticalityColor`                            |
| [`app/(app)/repo/[id]/graph.tsx`](<../../mobile/src/app/(app)/repo/[id]/graph.tsx>) | the screen: fetch, layout, controls                            |
| [`components/GraphInspector.tsx`](../../mobile/src/components/GraphInspector.tsx)   | the sheet for the selected node                                |

The data is the same `GET /graph?level=file|symbol` payload the web uses; see [the dependency graph](../graph/dependency-graph.md).

## Layout

`computeLayout(graph, options)` runs the simulation on the JavaScript thread without blocking the screen:

1. Nodes and links are copied into simulation objects. The simulation is created **stopped** with three dimensions.
2. Forces, tuned for a phone screen: link distance 45 and strength 0.25, many-body charge −110 (`chargeStrength`), and a centring force. At the web's defaults the graph collapses into one blob at phone size.
3. It ticks manually in chunks of 10 (`chunkSize`), calling `onProgress(done, total)` and yielding with `setTimeout(0)` between chunks. A macrotask, not a microtask: a microtask would drain before React could paint, and the progress bar would never move.
4. An `AbortSignal` is checked between chunks, so leaving the screen or switching level stops the work.
5. It returns positions as a `Float32Array`, links as numeric index pairs, the bounding radius and the number of ticks run.

`defaultTicks` trades quality for time as graphs grow:

| Nodes        | Ticks |
| ------------ | ----- |
| up to 1,000  | 300   |
| up to 5,000  | 200   |
| up to 10,000 | 150   |
| more         | 100   |

Two details are load-bearing:

- **The link force gets throwaway copies of the links.** d3 rewrites link endpoints into node object references; the returned links must keep numeric indices for the renderer.
- **The `id` accessor stays positional.** Setting it to the node's string id makes d3 resolve the numeric indices against that accessor and fail with `node not found`.

The screen shows a progress overlay with the node count and percentage while fetching and laying out, and drops `layout` to `null` before each new layout, which remounts the renderer.

## The renderer

There is no reconciler. When the `GLView` context is created, the scene is built once:

- **Renderer.** three's `WebGLRenderer` expects an `HTMLCanvasElement`, which React Native does not have, so a small canvas shim supplies the properties three reads. While constructing it, the global `WebGLRenderingContext` is hidden, so a context `instanceof` check (added in three r163) fails with a message that names the cause instead of failing obscurely.
- **Camera.** A perspective camera with a 50° field of view and a far plane of 20 bounding radii (at least 100).
- **Nodes.** One `InstancedMesh` of unit spheres with `MeshBasicMaterial`. Tessellation drops with size: 12×8 segments up to 2,000 nodes, 8×6 up to 8,000, 6×4 above, so a large graph does not spend its frame on triangles nobody can see.
- **Node size.** A base radius of `NODE_SIZE_FRACTION` (1.1 %) of the bounding radius, scaled by `sqrt(max(loc, 10)) / 10` and clamped to 0.55×–2.2×. Without the clamp one 2,000-line file swallows its neighbours.
- **Node colour.** Search match `#a855f7`, then selected `#0078ff`, then criticality: critical `#ef4444`, caution `#facc15`, otherwise `#22c55e`, the same mapping as the web.
- **Links.** One `LineSegments` for the whole edge set, dim `#2a3550`. A WebGL line is one pixel wide whatever width is requested, so links incident to the selected node are redrawn as thin cylinders in `#5aa2ff`, at most `MAX_WIDE_LINKS = 64`.
- **Haloes.** Search matches get pulsing rings: at most `MAX_HALO_MATCHES = 8` matches, `RINGS_PER_HALO = 3` rings each, on a 1,500 ms cycle. Up to `MAX_SEARCH_MATCHES = 24` nodes are coloured as matches.

After construction only what changes is touched: instance colours when the selection or search changes (only the instances whose colour changed are rewritten), and the link buffer when the selection changes. The per-frame cost is the draw. Draw calls are constant in node count: one for nodes, one for links, one for the wide links.

**`gl.endFrameEXP()` must be called after every render** to present the buffer. Omitting it gives a permanently blank view with no error, the most common way this integration fails silently.

On unmount the frame is cancelled and every geometry, material and the renderer are disposed. `LineSegments` has no `dispose()` of its own; its geometry and material do.

## Gestures and picking

Gestures go through a `PanResponder` over the `GLView`:

- **One-finger drag orbits** the camera. It uses the per-event delta, not `gesture.dx`: `dx` is the distance since the gesture began, and applying it on every move event spins the graph several turns on a short swipe. Elevation is clamped between 5° and 170° (`MIN_PHI`, `MAX_PHI`) so the camera cannot flip over the pole.
- **Two-finger spread zooms**, clamped between 0.15× and 12× of the bounding radius.
- **Tap picks.** Every node is projected to screen space and the nearest within `PICK_RADIUS = 44` points is selected. A release that moved more than 8 points in total is a drag, not a tap.

The orbit maths in `graphCamera.ts` is pure and unit-tested; the renderer itself picks with three's own projection, which is exact, and the two agree on where a node is.

## Controls

The screen floats its controls over the canvas:

- the **level switch** (files or symbols) at the top, with the **legend** under it;
- at file level, the **reading-order tour** under the switch. `guideSteps` sorts the guide by position and joins entries to nodes by path, dropping entries with no node, as the web does;
- **search** pinned to the bottom, matching labels and paths;
- **`GraphInspector`**, a sheet for the selected node.

The overlay adds no safe-area padding: the repository shell already applied the top inset, and adding it again leaves a status-bar-sized gap.

## Why three is pinned

`three` is pinned exactly to `0.162.0`, with `@types/three` to match. Release r163 removed WebGL 1 support, and `expo-gl` provides only WebGL 1, so with r163 or later `new THREE.WebGLRenderer()` throws `WebGL 1 is not supported since r163` before drawing anything.

- A dependency that wants a newer three is a conflict, not an upgrade.
- r162 dates from early 2024 and receives no fixes.
- The only way off the pin is a WebGL 2 context, which `expo-gl` does not offer.

## Why not a React 3D library

`@react-three/fiber/native` v9 throws at module scope under this stack, and its successor's own README says not to use it yet and points native users toward WebGPU. Imperative three over `expo-gl` is what works. The cost is that scene construction, colour updates, picking, disposal and the camera are hand-written; the benefit is that no component tree is reconciled on the draw path, which is what makes graphs of thousands of nodes viable.

## Testing

Jest has no GL context and no device, so the renderer is verified on a phone. The pure parts it depends on are tested: `graphLayout` (tick counts, chunking, abort, bounding radius), `graphSelection` (matching, incident links, tour steps) and `graphCamera` (orbit, clamping, projection).

## Design trade-offs and limits

- **Layout on the phone.** No server work and no cache, but a large repository spends seconds to a minute in the simulation every time the screen opens or the level changes.
- **Fewer ticks for big graphs.** Layout quality drops with size by design.
- **A frozen three.js.** No upstream fixes until `expo-gl` offers WebGL 2.
- **One-pixel lines.** Only the selection's links can be drawn wide.
- **No node cap.** The phone draws every node the API returns; the tessellation and the instanced mesh are what keep it drawable.

## Related documentation

- [The mobile app](overview.md): the rest of the app.
- [Rendering the graph](../graph/rendering.md): the web's renderers.
- [The dependency graph](../graph/dependency-graph.md): the payload.
