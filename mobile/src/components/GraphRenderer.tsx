/**
 * The dependency graph, drawn with raw three over an expo-gl context.
 *
 * @module GraphRenderer
 *
 * There is no reconciler in the path. The scene is built once with
 * imperative three calls, and a single animation frame owns the camera,
 * the haloes and the draw. That is the cost of not using a React 3D
 * library, and it buys a graph that draws tens of thousands of nodes
 * without a component tree to reconcile.
 *
 * Two details matter for correctness on `expo-gl`:
 *
 * 1. three's `WebGLRenderer` expects an `HTMLCanvasElement`, which does
 *    not exist here. A shim object supplies the handful of properties
 *    three reads.
 * 2. `gl.endFrameEXP()` must be called after every draw to present the
 *    buffer. Omitting it yields a permanently blank view with no error --
 *    the single most common way this integration fails silently.
 *
 * The matrix is set once, when the scene is built. After that only the
 * things that change are touched: the node colours when the selection or
 * the search changes, and the link colours when the selection changes.
 * The per-frame cost is the draw itself.
 */

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  PanResponder,
  StyleSheet,
  Text,
  View,
  type LayoutChangeEvent,
} from "react-native";
import { GLView } from "expo-gl";
import * as THREE from "three";

import { clampPhi } from "@/lib/graphCamera";
import type { IndexedLink } from "@/lib/graphLayout";
import {
  NODE_COLOR_MATCH,
  NODE_COLOR_SELECTED,
  criticalityColor,
  type GraphNodeMeta,
} from "@/lib/graphTypes";

/**
 * Sphere tessellation, by graph size.
 *
 * A force graph draws one sphere per node, so the detail has to come down
 * as the node count goes up: at a few hundred nodes a rounder sphere is
 * nearly free and reads far better than a faceted one, while at tens of
 * thousands the triangles are the whole cost.
 */
function sphereSegments(nodeCount: number): { segments: number; rings: number } {
  if (nodeCount <= 2_000) return { segments: 12, rings: 8 };
  if (nodeCount <= 8_000) return { segments: 8, rings: 6 };
  return { segments: 6, rings: 4 };
}

/** Nodes are this fraction of the graph's own extent in radius. */
const NODE_SIZE_FRACTION = 0.011;

/** How many search matches get a pulsing halo. The rest are coloured only. */
export const MAX_HALO_MATCHES = 8;

/** How many rings each halo is drawn with. */
const RINGS_PER_HALO = 3;

/** How many incident links are drawn wide. The rest are only recoloured. */
const MAX_WIDE_LINKS = 64;

/** How far a tap can be from a node and still pick it, in points. */
const PICK_RADIUS = 44;

/** The colour of a link that is not incident to the selection. */
const LINK_COLOR_DIM = new THREE.Color(0x2a3550);

/** The colour of a link incident to the selection. */
const LINK_COLOR_FOCUSED = new THREE.Color(0x5aa2ff);

/** The colour of the halo rings. */
const HALO_COLOR = new THREE.Color(NODE_COLOR_MATCH);

/** The slice of a GL context this file inspects. */
interface GLContext {
  drawingBufferWidth: number;
  drawingBufferHeight: number;
  canvas?: unknown;
  endFrameEXP: () => void;
}

/** The camera's placement, and where it is heading. */
interface CameraState {
  theta: number;
  phi: number;
  radius: number;
  /** The point the camera looks at. */
  target: THREE.Vector3;
  /** Where the camera is heading. */
  targetGoal: THREE.Vector3;
  /** The distance the camera is heading for. */
  radiusGoal: number;
}

/** Everything the renderer owns on the GPU. */
interface Scene {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  geometry: THREE.SphereGeometry;
  nodeMaterial: THREE.MeshBasicMaterial;
  nodeMesh: THREE.InstancedMesh;
  linkGeometry: THREE.BufferGeometry;
  linkMaterial: THREE.LineBasicMaterial;
  linkMesh: THREE.LineSegments;
  /** Per-vertex colours of the link buffer, three floats per vertex. */
  linkColors: Float32Array;
  /** The base colour of every node, three floats per node. */
  baseColors: Float32Array;
  /** The nodes whose colour is currently overridden. */
  overridden: Set<number>;
  /** The links whose colour is currently overridden. */
  litLinks: Set<number>;
  incidentGeometry: THREE.CylinderGeometry;
  incidentMaterial: THREE.MeshBasicMaterial;
  incidentMesh: THREE.InstancedMesh;
  haloGeometry: THREE.RingGeometry;
  /** One material per halo ring: each ring fades on its own schedule. */
  haloMaterials: THREE.MeshBasicMaterial[];
  /** The pool of halo rings, reused for every match. */
  halos: THREE.Mesh[];
  /** The world radius of each node, used to size its halo. */
  nodeRadii: Float32Array;
}

/** Props for {@link GraphRenderer}. */
export interface GraphRendererProps {
  /** `xyz` triples, one per node, in node order. */
  positions: Float32Array;
  /** Links resolved to node indices. */
  links: IndexedLink[];
  /** Node metadata, used for colour and size. */
  nodes: GraphNodeMeta[];
  /** Radius that contains every node, used to frame the camera. */
  boundingRadius: number;
  /** The node the reader has picked, if any. */
  selectedNodeId: string | null;
  /** The nodes the current search matched. */
  matchNodeIds: readonly string[];
  /** Called with the picked node, or null when the reader taps the background. */
  onSelect: (nodeId: string | null) => void;
}

/** The imperative handle the screen drives the camera with. */
export interface GraphRendererHandle {
  /** Move the camera to a node and frame it. */
  focusNode: (nodeId: string) => void;
  /** Return the camera to the whole graph. */
  resetCamera: () => void;
}

/**
 * Construct a three renderer.
 *
 * `three` is pinned to `0.162.x` -- the last release supporting WebGL 1,
 * which is the level expo-gl provides. At that version the WebGL 2 guard
 * does not exist and this is a plain construction.
 *
 * The global `WebGLRenderingContext` is hidden for the duration, because
 * r163+ added a `context instanceof WebGLRenderingContext` check that
 * throws, and a future three bump would otherwise reintroduce the failure
 * in a place that gives no hint of its cause.
 *
 * @param canvas - Canvas shim for three.
 * @param gl - The expo-gl context.
 * @returns A constructed renderer.
 */
function createRenderer(
  canvas: HTMLCanvasElement,
  gl: GLContext,
): THREE.WebGLRenderer {
  const scope = globalThis as unknown as Record<string, unknown>;
  const had = "WebGLRenderingContext" in scope;
  const saved = scope.WebGLRenderingContext;

  try {
    if (had) scope.WebGLRenderingContext = undefined;
    return new THREE.WebGLRenderer({
      canvas,
      context: gl as unknown as WebGLRenderingContext,
      antialias: false,
      alpha: false,
      powerPreference: "high-performance",
    });
  } finally {
    if (had) scope.WebGLRenderingContext = saved;
  }
}

/**
 * The graph, drawn in 3D.
 *
 * @param props - The layout, the nodes, and the current selection.
 * @param ref - The imperative handle the screen drives the camera with.
 * @returns A GL surface, or an error message if the context could not be built.
 */
export const GraphRenderer = forwardRef<
  GraphRendererHandle,
  GraphRendererProps
>(function GraphRenderer(
  {
    positions,
    links,
    nodes,
    boundingRadius,
    selectedNodeId,
    matchNodeIds,
    onSelect,
  },
  ref,
) {
  const [error, setError] = useState<string | null>(null);

  const sceneRef = useRef<Scene | null>(null);
  const rafRef = useRef(0);
  const startedAtRef = useRef(0);
  const spreadRef = useRef<number | undefined>(undefined);
  const surfaceSizeRef = useRef({ width: 0, height: 0 });

  const cameraStateRef = useRef<CameraState>({
    theta: 0,
    phi: (35 * Math.PI) / 180,
    radius: Math.max(boundingRadius * 2.4, 1),
    target: new THREE.Vector3(0, 0, 0),
    targetGoal: new THREE.Vector3(0, 0, 0),
    radiusGoal: Math.max(boundingRadius * 2.4, 1),
  });

  // ``gesture.dx``/``dy`` are the distance since the gesture *started*, not
  // since the last event. Applying them per move event adds the whole drag
  // again on every frame, which makes a short swipe spin the graph several
  // turns. Tracking the previous value gives the per-event delta.
  const lastDragRef = useRef({ dx: 0, dy: 0 });

  /**
   * Re-applies the current selection and search to a freshly built scene.
   *
   * The scene is built asynchronously by ``onContextCreate``, after the
   * colour effects have already run once and no-opped against a null scene.
   * Without this call, a selection or match list that was already non-empty
   * when the renderer mounted would not be painted until it next changed.
   */
  const refreshVisualsRef = useRef<() => void>(() => {});

  const propsRef = useRef({
    positions,
    links,
    nodes,
    boundingRadius,
    selectedNodeId,
    matchNodeIds,
    onSelect,
  });
  useEffect(() => {
    propsRef.current = {
      positions,
      links,
      nodes,
      boundingRadius,
      selectedNodeId,
      matchNodeIds,
      onSelect,
    };
  });

  // Index of every node by its identifier, so a selection resolves to a
  // node without a scan.
  const indexById = useMemo(() => {
    const map = new Map<string, number>();
    nodes.forEach((node, index) => map.set(node.id, index));
    return map;
  }, [nodes]);

  /**
   * Release the GPU resources.
   *
   * Called on unmount only. `LineSegments` has no `dispose` of its own --
   * calling one would throw -- but its geometry and material do, and those
   * are what own the buffers. `InstancedMesh` is the exception: it has a
   * `dispose` for its instance buffers.
   */
  const dispose = useCallback(() => {
    cancelAnimationFrame(rafRef.current);
    const scene = sceneRef.current;
    if (!scene) return;

    scene.nodeMesh.dispose();
    scene.geometry.dispose();
    scene.nodeMaterial.dispose();
    scene.linkGeometry.dispose();
    scene.linkMaterial.dispose();
    scene.incidentMesh.dispose();
    scene.incidentGeometry.dispose();
    scene.incidentMaterial.dispose();
    scene.haloGeometry.dispose();
    scene.haloMaterials.forEach((material) => material.dispose());
    scene.renderer.dispose();
    sceneRef.current = null;
  }, []);

  useEffect(() => dispose, [dispose]);

  /**
   * Build the scene once the GL context exists.
   *
   * @param gl - The expo-gl context.
   */
  const onContextCreate = useCallback((gl: GLContext) => {
    try {
      const current = propsRef.current;
      const width = gl.drawingBufferWidth;
      const height = gl.drawingBufferHeight;

      // Three reads these properties off the canvas; nothing else is
      // required of it.
      const canvasShim = {
        width,
        height,
        style: {},
        addEventListener: () => {},
        removeEventListener: () => {},
        clientHeight: height,
        clientWidth: width,
        getContext: () => gl,
      } as unknown as HTMLCanvasElement;
      (gl as unknown as { canvas: unknown }).canvas = canvasShim;

      let renderer: THREE.WebGLRenderer;
      try {
        renderer = createRenderer(canvasShim, gl);
      } catch (cause) {
        throw new Error(cause instanceof Error ? cause.message : String(cause));
      }
      renderer.setSize(width, height, false);
      // expo-gl already renders at the device's native resolution, so a
      // pixel ratio above 1 would multiply fill cost for no visible gain.
      renderer.setPixelRatio(1);
      renderer.setClearColor(0x09090b, 1);

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(
        50,
        width / height,
        0.1,
        Math.max(current.boundingRadius * 20, 100),
      );

      // ── Nodes ──
      const tessellation = sphereSegments(current.nodes.length);
      const geometry = new THREE.SphereGeometry(
        1,
        tessellation.segments,
        tessellation.rings,
      );
      const nodeMaterial = new THREE.MeshBasicMaterial({ toneMapped: false });
      const nodeMesh = new THREE.InstancedMesh(
        geometry,
        nodeMaterial,
        Math.max(current.nodes.length, 1),
      );
      nodeMesh.instanceMatrix.setUsage(THREE.StaticDrawUsage);

      const matrix = new THREE.Matrix4();
      const color = new THREE.Color();
      const baseColors = new Float32Array(current.nodes.length * 3);
      const nodeRadii = new Float32Array(current.nodes.length);

      // A node's radius is a fraction of the graph's own extent, so the
      // same scene reads the same at sixty nodes and at six thousand. The
      // per-node term grows with the square root of the line count and is
      // clamped, so one very large file does not swallow its neighbours.
      const baseRadius = current.boundingRadius * NODE_SIZE_FRACTION;
      const radiusFor = (loc: number): number => {
        const growth = Math.sqrt(Math.max(loc || 0, 10)) / 10;
        return baseRadius * Math.min(Math.max(growth, 0.55), 2.2);
      };

      for (let i = 0; i < current.nodes.length; i += 1) {
        const r = radiusFor(current.nodes[i].loc);
        nodeRadii[i] = r;
        matrix.makeScale(r, r, r);
        matrix.setPosition(
          current.positions[i * 3],
          current.positions[i * 3 + 1],
          current.positions[i * 3 + 2],
        );
        nodeMesh.setMatrixAt(i, matrix);
        color.set(criticalityColor(current.nodes[i].criticality));
        nodeMesh.setColorAt(i, color);
        baseColors[i * 3] = color.r;
        baseColors[i * 3 + 1] = color.g;
        baseColors[i * 3 + 2] = color.b;
      }
      nodeMesh.count = current.nodes.length;
      nodeMesh.instanceMatrix.needsUpdate = true;
      if (nodeMesh.instanceColor) nodeMesh.instanceColor.needsUpdate = true;
      scene.add(nodeMesh);

      // ── Links ──
      // One LineSegments draw call for the whole edge set. Individual lines
      // would be thousands of draw calls and would make this renderer look
      // far worse than it is.
      const linkPositions = new Float32Array(current.links.length * 6);
      const linkColors = new Float32Array(current.links.length * 6);
      for (let i = 0; i < current.links.length; i += 1) {
        const { source, target } = current.links[i];
        linkPositions[i * 6] = current.positions[source * 3];
        linkPositions[i * 6 + 1] = current.positions[source * 3 + 1];
        linkPositions[i * 6 + 2] = current.positions[source * 3 + 2];
        linkPositions[i * 6 + 3] = current.positions[target * 3];
        linkPositions[i * 6 + 4] = current.positions[target * 3 + 1];
        linkPositions[i * 6 + 5] = current.positions[target * 3 + 2];
        for (let v = 0; v < 2; v += 1) {
          linkColors[i * 6 + v * 3] = LINK_COLOR_DIM.r;
          linkColors[i * 6 + v * 3 + 1] = LINK_COLOR_DIM.g;
          linkColors[i * 6 + v * 3 + 2] = LINK_COLOR_DIM.b;
        }
      }
      const linkGeometry = new THREE.BufferGeometry();
      linkGeometry.setAttribute(
        "position",
        new THREE.BufferAttribute(linkPositions, 3),
      );
      linkGeometry.setAttribute(
        "color",
        new THREE.BufferAttribute(linkColors, 3),
      );
      const linkMaterial = new THREE.LineBasicMaterial({
        vertexColors: true,
        transparent: true,
        opacity: 0.9,
      });
      const linkMesh = new THREE.LineSegments(linkGeometry, linkMaterial);
      scene.add(linkMesh);

      // ── Incident links ──
      // A WebGL line is one pixel wide whatever you ask for, so the links
      // that touch the selection are drawn as thin cylinders instead. One
      // instanced mesh, so the whole set is a single draw call.
      const incidentGeometry = new THREE.CylinderGeometry(1, 1, 1, 6);
      const incidentMaterial = new THREE.MeshBasicMaterial({
        color: LINK_COLOR_FOCUSED,
        toneMapped: false,
        transparent: true,
        opacity: 0.85,
      });
      const incidentMesh = new THREE.InstancedMesh(
        incidentGeometry,
        incidentMaterial,
        MAX_WIDE_LINKS,
      );
      incidentMesh.count = 0;
      scene.add(incidentMesh);

      // ── Haloes ──
      const haloGeometry = new THREE.RingGeometry(1, 1.18, 32);
      const haloMaterials: THREE.MeshBasicMaterial[] = [];
      const halos: THREE.Mesh[] = [];
      for (let i = 0; i < MAX_HALO_MATCHES * RINGS_PER_HALO; i += 1) {
        const material = new THREE.MeshBasicMaterial({
          color: HALO_COLOR,
          transparent: true,
          opacity: 0,
          side: THREE.DoubleSide,
          depthWrite: false,
          toneMapped: false,
        });
        haloMaterials.push(material);
        const ring = new THREE.Mesh(haloGeometry, material);
        ring.visible = false;
        ring.userData.phase = (i % RINGS_PER_HALO) / RINGS_PER_HALO;
        halos.push(ring);
        scene.add(ring);
      }

      sceneRef.current = {
        renderer,
        scene,
        camera,
        geometry,
        nodeMaterial,
        nodeMesh,
        linkGeometry,
        linkMaterial,
        linkMesh,
        linkColors,
        baseColors,
        overridden: new Set(),
        litLinks: new Set(),
        incidentGeometry,
        incidentMaterial,
        incidentMesh,
        haloGeometry,
        haloMaterials,
        halos,
        nodeRadii,
      };

      startedAtRef.current = Date.now();

      // Paint whatever the selection and the search already say.
      refreshVisualsRef.current();

      const animate = () => {
        const active = sceneRef.current;
        if (!active) return;

        const state = cameraStateRef.current;

        // Ease the camera toward its goal so focusing a node glides
        // rather than jumps.
        state.target.lerp(state.targetGoal, 0.12);
        state.radius += (state.radiusGoal - state.radius) * 0.12;

        const cosPhi = Math.cos(state.phi);
        active.camera.position.set(
          state.target.x - state.radius * cosPhi * Math.sin(state.theta),
          state.target.y + state.radius * Math.sin(state.phi),
          state.target.z + state.radius * cosPhi * Math.cos(state.theta),
        );
        active.camera.lookAt(state.target);

        // ── Haloes ──
        const now = Date.now() - startedAtRef.current;
        active.halos.forEach((ring) => {
          if (!ring.visible) return;
          ring.quaternion.copy(active.camera.quaternion);
          const phase = ring.userData.phase as number;
          const t = (now / 1500 + phase) % 1;
          const base = ring.userData.baseRadius as number;
          ring.scale.setScalar(base * (1 + t * 2.5));
          (ring.material as THREE.MeshBasicMaterial).opacity = (1 - t) * 0.6;
        });

        active.renderer.render(active.scene, active.camera);
        gl.endFrameEXP();

        rafRef.current = requestAnimationFrame(animate);
      };

      rafRef.current = requestAnimationFrame(animate);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unknown GL error");
    }
  }, []);

  /**
   * Repaint the nodes the search or the selection has claimed.
   *
   * Only the nodes whose colour actually changed are touched: the base
   * colours are kept alongside, so a node that was highlighted and is not
   * any more goes back to what it was.
   */
  const applyNodeColours = useCallback(() => {
    const active = sceneRef.current;
    if (!active) return;

    const current = propsRef.current;

    const wanted = new Map<number, string>();
    for (const id of current.matchNodeIds) {
      const index = indexById.get(id);
      if (index !== undefined) wanted.set(index, NODE_COLOR_MATCH);
    }
    if (current.selectedNodeId) {
      const index = indexById.get(current.selectedNodeId);
      if (index !== undefined) wanted.set(index, NODE_COLOR_SELECTED);
    }

    const color = new THREE.Color();

    // Put back the nodes that were highlighted and are not any more.
    for (const index of active.overridden) {
      if (wanted.has(index)) continue;
      color.setRGB(
        active.baseColors[index * 3],
        active.baseColors[index * 3 + 1],
        active.baseColors[index * 3 + 2],
      );
      active.nodeMesh.setColorAt(index, color);
    }

    // And paint the ones that are highlighted now.
    for (const [index, hex] of wanted) {
      color.set(hex);
      active.nodeMesh.setColorAt(index, color);
    }

    active.overridden = new Set(wanted.keys());
    if (active.nodeMesh.instanceColor) {
      active.nodeMesh.instanceColor.needsUpdate = true;
    }
  }, [indexById]);

  /**
   * Focus the links that touch the selection.
   *
   * The colour of every incident link is rewritten, and the first few are
   * also drawn wide. Rebuilding the whole link buffer would upload the
   * entire edge set to the GPU on every tap, which is the thing this
   * deliberately avoids.
   */
  const applyLinkFocus = useCallback(() => {
    const active = sceneRef.current;
    if (!active) return;

    const current = propsRef.current;
    const selectedIndex = current.selectedNodeId
      ? indexById.get(current.selectedNodeId)
      : undefined;

    const incident: number[] = [];
    if (selectedIndex !== undefined) {
      for (let i = 0; i < current.links.length; i += 1) {
        const { source, target } = current.links[i];
        if (source === selectedIndex || target === selectedIndex) {
          incident.push(i);
        }
      }
    }
    const incidentSet = new Set(incident);

    // Put back the links that were lit and are not any more.
    for (const index of active.litLinks) {
      if (incidentSet.has(index)) continue;
      for (let v = 0; v < 2; v += 1) {
        active.linkColors[index * 6 + v * 3] = LINK_COLOR_DIM.r;
        active.linkColors[index * 6 + v * 3 + 1] = LINK_COLOR_DIM.g;
        active.linkColors[index * 6 + v * 3 + 2] = LINK_COLOR_DIM.b;
      }
    }
    for (const index of incident) {
      for (let v = 0; v < 2; v += 1) {
        active.linkColors[index * 6 + v * 3] = LINK_COLOR_FOCUSED.r;
        active.linkColors[index * 6 + v * 3 + 1] = LINK_COLOR_FOCUSED.g;
        active.linkColors[index * 6 + v * 3 + 2] = LINK_COLOR_FOCUSED.b;
      }
    }
    active.litLinks = incidentSet;

    const attribute = active.linkGeometry.getAttribute(
      "color",
    ) as THREE.BufferAttribute;
    attribute.needsUpdate = true;

    // The wide links, as one instanced draw.
    const wide = incident.slice(0, MAX_WIDE_LINKS);
    const matrix = new THREE.Matrix4();
    const quaternion = new THREE.Quaternion();
    const up = new THREE.Vector3(0, 1, 0);
    const direction = new THREE.Vector3();
    const midpoint = new THREE.Vector3();
    const scale = new THREE.Vector3();

    wide.forEach((linkIndex, slot) => {
      const { source, target } = current.links[linkIndex];
      const sx = current.positions[source * 3];
      const sy = current.positions[source * 3 + 1];
      const sz = current.positions[source * 3 + 2];
      const tx = current.positions[target * 3];
      const ty = current.positions[target * 3 + 1];
      const tz = current.positions[target * 3 + 2];

      direction.set(tx - sx, ty - sy, tz - sz);
      const length = direction.length() || 1;
      direction.normalize();
      quaternion.setFromUnitVectors(up, direction);
      midpoint.set((sx + tx) / 2, (sy + ty) / 2, (sz + tz) / 2);
      const thickness = Math.max(active.nodeRadii[source] * 0.12, 0.05);
      scale.set(thickness, length, thickness);

      matrix.compose(midpoint, quaternion, scale);
      active.incidentMesh.setMatrixAt(slot, matrix);
    });

    active.incidentMesh.count = wide.length;
    active.incidentMesh.instanceMatrix.needsUpdate = true;
  }, [indexById]);

  /**
   * Place the halo rings on the nodes the search matched.
   *
   * The rings are a fixed pool: the number of matches that get one is
   * capped, because a search that matches everything would otherwise ask
   * for a ring per node.
   */
  const applyHalos = useCallback(() => {
    const active = sceneRef.current;
    if (!active) return;

    const current = propsRef.current;
    const haloed = current.matchNodeIds.slice(0, MAX_HALO_MATCHES);

    active.halos.forEach((ring, slot) => {
      const matchIndex = Math.floor(slot / RINGS_PER_HALO);
      const nodeId = haloed[matchIndex];
      const index = nodeId ? indexById.get(nodeId) : undefined;

      if (index === undefined) {
        ring.visible = false;
        return;
      }

      ring.visible = true;
      ring.position.set(
        current.positions[index * 3],
        current.positions[index * 3 + 1],
        current.positions[index * 3 + 2],
      );
      ring.userData.baseRadius = Math.max(active.nodeRadii[index] * 1.4, 0.4);
    });
  }, [indexById]);

  // Kept current on every render so ``onContextCreate`` can repaint a scene
  // it has just built without waiting for a prop change.
  refreshVisualsRef.current = () => {
    applyNodeColours();
    applyLinkFocus();
    applyHalos();
  };

  useEffect(() => {
    applyNodeColours();
    applyLinkFocus();
    applyHalos();
  }, [
    applyNodeColours,
    applyLinkFocus,
    applyHalos,
    selectedNodeId,
    matchNodeIds,
  ]);

  /**
   * Find the node nearest a point on screen.
   *
   * @param x - Touch x, in points.
   * @param y - Touch y, in points.
   * @returns The node's identifier, or null.
   */
  const pick = useCallback((x: number, y: number): string | null => {
    const active = sceneRef.current;
    if (!active) return null;

    const current = propsRef.current;
    const { width, height } = surfaceSizeRef.current;
    if (width <= 0 || height <= 0) return null;

    const vector = new THREE.Vector3();
    let bestId: string | null = null;
    let bestDistance = PICK_RADIUS * PICK_RADIUS;

    for (let i = 0; i < current.nodes.length; i += 1) {
      vector.set(
        current.positions[i * 3],
        current.positions[i * 3 + 1],
        current.positions[i * 3 + 2],
      );
      vector.project(active.camera);
      if (vector.z > 1) continue;
      const screenX = ((vector.x + 1) / 2) * width;
      const screenY = ((1 - vector.y) / 2) * height;
      const dx = screenX - x;
      const dy = screenY - y;
      const distance = dx * dx + dy * dy;
      if (distance < bestDistance) {
        bestDistance = distance;
        bestId = current.nodes[i].id;
      }
    }

    return bestId;
  }, []);

  const panResponder = useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        onMoveShouldSetPanResponder: () => true,
        onPanResponderGrant: () => {
          lastDragRef.current = { dx: 0, dy: 0 };
        },
        onPanResponderMove: (event, gesture) => {
          const state = cameraStateRef.current;
          const touches = event.nativeEvent.touches;

          if (touches.length >= 2) {
            // Pinch: the distance between the two fingers sets the zoom.
            const [a, b] = touches;
            const dx = a.pageX - b.pageX;
            const dy = a.pageY - b.pageY;
            const spread = Math.sqrt(dx * dx + dy * dy);
            const previous = spreadRef.current;
            if (previous && previous > 0) {
              const factor = previous / Math.max(spread, 1);
              const bounds = propsRef.current.boundingRadius;
              state.radiusGoal = Math.min(
                Math.max(state.radiusGoal * factor, bounds * 0.15),
                bounds * 12,
              );
            }
            spreadRef.current = spread;
            return;
          }

          spreadRef.current = undefined;

          const last = lastDragRef.current;
          const deltaX = gesture.dx - last.dx;
          const deltaY = gesture.dy - last.dy;
          last.dx = gesture.dx;
          last.dy = gesture.dy;

          state.theta -= deltaX * 0.005;
          state.phi = clampPhi(state.phi + deltaY * 0.005);
        },
        onPanResponderRelease: (event, gesture) => {
          spreadRef.current = undefined;
          lastDragRef.current = { dx: 0, dy: 0 };

          // A movement of less than a touch slop is a tap, not a drag.
          const moved = Math.abs(gesture.dx) + Math.abs(gesture.dy);
          if (moved > 8) return;

          const { locationX, locationY } = event.nativeEvent;
          propsRef.current.onSelect(pick(locationX, locationY));
        },
        onPanResponderTerminate: () => {
          spreadRef.current = undefined;
        },
      }),
    [pick],
  );

  /**
   * Record the size of the touch surface, so a tap can be turned into a
   * screen position.
   *
   * @param event - The layout event.
   */
  const handleLayout = (event: LayoutChangeEvent) => {
    const { width, height } = event.nativeEvent.layout;
    surfaceSizeRef.current = { width, height };
  };

  useImperativeHandle(
    ref,
    () => ({
      focusNode: (nodeId: string) => {
        const active = sceneRef.current;
        const current = propsRef.current;
        const index = indexById.get(nodeId);
        if (!active || index === undefined) return;
        cameraStateRef.current.targetGoal.set(
          current.positions[index * 3],
          current.positions[index * 3 + 1],
          current.positions[index * 3 + 2],
        );
        cameraStateRef.current.radiusGoal = Math.max(
          current.boundingRadius * 0.6,
          1,
        );
      },
      resetCamera: () => {
        cameraStateRef.current.targetGoal.set(0, 0, 0);
        cameraStateRef.current.radiusGoal = Math.max(
          propsRef.current.boundingRadius * 2.4,
          1,
        );
      },
    }),
    [indexById],
  );

  if (error) {
    return (
      <View style={styles.errorBox}>
        <Text style={styles.errorTitle}>The graph could not be drawn</Text>
        <Text style={styles.errorBody}>{error}</Text>
      </View>
    );
  }

  return (
    <View style={styles.root} testID="graph-renderer">
      <GLView
        style={StyleSheet.absoluteFill}
        onContextCreate={onContextCreate as (gl: unknown) => void}
      />
      {/* A transparent view over the GL surface carries the gestures, so
          the canvas does not have to know about touch handling at all. */}
      <View
        testID="graph-surface"
        style={StyleSheet.absoluteFill}
        onLayout={handleLayout}
        {...panResponder.panHandlers}
      />
    </View>
  );
});

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: "#09090b",
  },
  errorBox: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
    backgroundColor: "#0e0e10",
  },
  errorTitle: {
    color: "#f87171",
    fontSize: 16,
    fontWeight: "600",
    marginBottom: 8,
  },
  errorBody: {
    color: "#a1a1aa",
    fontSize: 13,
    textAlign: "center",
  },
});

export default GraphRenderer;
