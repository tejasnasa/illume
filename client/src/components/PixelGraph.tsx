/**
 * The pixel constellation: a dependency graph drawn on a coarse pixel grid,
 * slowly turning, with a soft light that wanders across it (or follows the
 * cursor) and names the file it lands on.
 * @module PixelGraph
 */
"use client";

import {
  drawFrame,
  heroScene,
  sampleScene,
  sceneFromGraph,
  yawToward,
  type FrameInput,
  type PixelScene,
} from "@/lib/pixelGraph";
import type Graph from "@/types/graph";
import { useEffect, useLayoutEffect, useMemo, useRef } from "react";

/** How long the cursor keeps steering after it last moved, in milliseconds. */
const CURSOR_HOLD_MS = 3500;
/** Per-frame share of the way the camera moves to where it is aimed. */
const CAMERA_EASE = 0.06;

/** The fixed camera and clock a still frame is drawn with. */
const STILL_YAW = 0.7;
const STILL_PITCH = 0.3;
const STILL_T = 4000;

/** How far a drag turns the camera, per CSS pixel moved. */
const DRAG_RADIANS_PER_PX = 0.008;

/** How far a drag may tip the camera up or down, so the scene never flips. */
const DRAG_PITCH_LIMIT = 0.9;

/** Extra per-frame drawing a caller supplies, read fresh every frame. */
export type PixelDecoration = Pick<
  FrameInput,
  "style" | "pinned" | "dimUnstyled" | "followed"
>;

/** Props for {@link PixelGraph}. */
export interface PixelGraphProps {
  /**
   * What to draw: a repository's file graph, or one of the built-in scenes.
   * `"hero"` is a labelled slice of Illume itself; `"sample"` is a small
   * anonymous constellation for preview cards.
   */
  source: Graph | "hero" | "sample";
  /** Turns the camera and moves the light with the cursor, anywhere on the page. */
  followCursor?: boolean;
  /** Spins steadily on its own, the way a preview card does, rather than drifting. */
  spin?: boolean;
  /** Lets a pointer drag turn the scene, on top of whatever it is doing on its own. */
  draggable?: boolean;
  /**
   * Draws one fixed frame, redrawn only when the canvas changes size, so
   * many can share a page without any of them running an animation loop.
   */
  still?: boolean;
  /** Low-resolution pixel size, in CSS pixels. */
  cell?: number;
  /** Letters each directory hub. */
  hubLabels?: boolean;
  /** Boxes and names the file nearest the light. */
  focusLabel?: boolean;
  /** Horizontal spread, as a fraction of the width. */
  spreadX?: number;
  /** Vertical spread, as a fraction of the height. */
  spreadY?: number;
  /** Light radius, as a fraction of the shorter side. */
  lightRadius?: number;
  /** A file to turn towards, by path; the camera eases round to face it. */
  turnTo?: string | null;
  /** How much of the scene to show, for a map that fills in as it is found. */
  reveal?: FrameInput["reveal"];
  /** Per-frame styling, as the chat uses to light the files an agent reads. */
  decorate?: (scene: PixelScene) => PixelDecoration;
  className?: string;
}

/**
 * Renders the constellation into a canvas that fills its positioned parent.
 *
 * The canvas is decorative and hidden from assistive technology. Drawing
 * pauses while it is off screen, and honours reduced motion by holding still.
 * Only a draggable canvas takes pointer input; any other lets it pass through.
 *
 * @returns The canvas.
 */
export default function PixelGraph({
  source,
  followCursor = false,
  spin = false,
  draggable = false,
  still = false,
  cell = 4,
  hubLabels = true,
  focusLabel = true,
  spreadX = 0.36,
  spreadY = 0.4,
  lightRadius = 0.3,
  turnTo = null,
  reveal,
  decorate,
  className = "",
}: PixelGraphProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const scene = useMemo(
    () =>
      source === "hero"
        ? heroScene()
        : source === "sample"
          ? sampleScene()
          : sceneFromGraph(source),
    [source],
  );

  // The loop reads the newest props from here, so it never restarts for them.
  const live = useRef({
    followCursor,
    spin,
    draggable,
    cell,
    hubLabels,
    focusLabel,
    spreadX,
    spreadY,
    lightRadius,
    turnTo,
    reveal,
    decorate,
  });
  useLayoutEffect(() => {
    live.current = {
      followCursor,
      spin,
      draggable,
      cell,
      hubLabels,
      focusLabel,
      spreadX,
      spreadY,
      lightRadius,
      turnTo,
      reveal,
      decorate,
    };
  });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const off = document.createElement("canvas");
    const reduce =
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const font = `${getComputedStyle(canvas).fontFamily || "ui-monospace"}, ui-monospace, monospace`;
    const t0 = performance.now();
    const cursor = { x: 0, y: 0, at: 0 };
    let yaw = 0;
    let pitch = 0;
    let turn = 0;
    let raf = 0;
    let visible = true;
    // What a drag has added to the camera; it stays where the drag left it.
    const drag = { id: -1, x: 0, y: 0, yaw: 0, pitch: 0 };

    const onMove = (e: PointerEvent) => {
      cursor.x = e.clientX;
      cursor.y = e.clientY;
      cursor.at = performance.now();
    };
    const onLeave = () => {
      cursor.at = 0;
    };
    const onDown = (e: PointerEvent) => {
      if (!live.current.draggable) return;
      drag.id = e.pointerId;
      drag.x = e.clientX;
      drag.y = e.clientY;
      canvas.setPointerCapture?.(e.pointerId);
    };
    const onDrag = (e: PointerEvent) => {
      if (e.pointerId !== drag.id) return;
      drag.yaw += (e.clientX - drag.x) * DRAG_RADIANS_PER_PX;
      drag.pitch = Math.max(
        -DRAG_PITCH_LIMIT,
        Math.min(
          DRAG_PITCH_LIMIT,
          drag.pitch + (e.clientY - drag.y) * DRAG_RADIANS_PER_PX,
        ),
      );
      drag.x = e.clientX;
      drag.y = e.clientY;
    };
    const onUp = (e: PointerEvent) => {
      if (e.pointerId === drag.id) drag.id = -1;
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    document.documentElement.addEventListener("mouseleave", onLeave);
    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointermove", onDrag);
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("pointercancel", onUp);

    const frame = () => {
      if (!still) raf = requestAnimationFrame(frame);
      if (!visible && !still) return;
      const p = live.current;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const W = Math.round(canvas.clientWidth * dpr);
      const H = Math.round(canvas.clientHeight * dpr);
      if (!W || !H) return;
      if (canvas.width !== W || canvas.height !== H) {
        canvas.width = W;
        canvas.height = H;
      }
      const px = Math.max(2, Math.round(p.cell * dpr));
      const lw = Math.ceil(W / px);
      const lh = Math.ceil(H / px);
      const now = performance.now();
      const t = now - t0;
      let light: { x: number; y: number } | null;

      // Ease round to whichever file the caller asked to face.
      const target = p.turnTo ? scene.byPath.get(p.turnTo) : undefined;
      if (target) {
        const want = yawToward(target);
        // The shortest way round, so the camera never spins the long way.
        const delta = Math.atan2(Math.sin(want - turn), Math.cos(want - turn));
        turn += delta * (reduce ? 1 : 0.04);
      }

      if (still) {
        // A three-quarter view with the light off to one side, the way a
        // preview card catches a scene mid-turn.
        yaw = STILL_YAW;
        pitch = STILL_PITCH;
        light = { x: lw * 0.62, y: lh * 0.42 };
      } else if (p.spin) {
        const tt = reduce ? 4000 : t;
        yaw = tt * 0.00028 + turn + drag.yaw;
        pitch = 0.35 * Math.sin(tt * 0.0002) + drag.pitch;
        light = reduce
          ? null
          : {
              x: lw * (0.5 + 0.34 * Math.cos(t * 0.0006)),
              y: lh * (0.5 + 0.3 * Math.sin(t * 0.0009)),
            };
      } else {
        const active =
          p.followCursor && cursor.at > 0 && now - cursor.at < CURSOR_HOLD_MS;
        const vw = window.innerWidth || 1;
        const vh = window.innerHeight || 1;
        const nx = active ? cursor.x / vw : 0.5 + 0.12 * Math.sin(t * 0.0003);
        const ny = active ? cursor.y / vh : 0.5 + 0.08 * Math.cos(t * 0.00025);
        const drift = reduce ? 0 : t * 0.00005;
        yaw += ((nx - 0.5) * 1.5 + drift + turn + drag.yaw - yaw) * CAMERA_EASE;
        pitch += ((ny - 0.5) * 0.9 + drag.pitch - pitch) * CAMERA_EASE;
        if (active) {
          const rect = canvas.getBoundingClientRect();
          light = {
            x: ((cursor.x - rect.left) / rect.width) * lw,
            y: ((cursor.y - rect.top) / rect.height) * lh,
          };
        } else if (reduce) {
          light = null;
        } else {
          light = {
            x: lw * (0.5 + 0.34 * Math.cos(t * 0.00042)),
            y: lh * (0.5 + 0.3 * Math.sin(t * 0.00067)),
          };
        }
      }

      drawFrame(canvas, off, scene, {
        t: still ? STILL_T : t,
        yaw,
        pitch,
        light,
        cell: px,
        dpr,
        spreadX: p.spreadX,
        spreadY: p.spreadY,
        lightRadius: p.lightRadius,
        glowEase: p.spin || still ? 1 : 0.2,
        hubLabels: p.hubLabels,
        focusLabel: p.focusLabel,
        font,
        reduce,
        reveal: p.reveal,
        ...p.decorate?.(scene),
      });
    };
    raf = requestAnimationFrame(frame);

    // A still frame has no loop to notice a resize, so it is told instead.
    const resized =
      still && typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(() => frame())
        : null;
    resized?.observe(canvas);

    const io =
      typeof IntersectionObserver === "undefined"
        ? null
        : new IntersectionObserver(([entry]) => {
            visible = entry.isIntersecting;
          });
    io?.observe(canvas);

    return () => {
      cancelAnimationFrame(raf);
      resized?.disconnect();
      io?.disconnect();
      window.removeEventListener("pointermove", onMove);
      document.documentElement.removeEventListener("mouseleave", onLeave);
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointermove", onDrag);
      canvas.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("pointercancel", onUp);
    };
  }, [scene, still]);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className={`absolute inset-0 block h-full w-full font-pixel ${
        draggable
          ? "cursor-grab touch-none active:cursor-grabbing"
          : "pointer-events-none"
      } ${className}`}
    />
  );
}
