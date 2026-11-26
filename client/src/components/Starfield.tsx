/**
 * A faint field of twinkling pixel stars, for the backdrop of a page.
 * @module Starfield
 */
"use client";

import { useEffect, useRef } from "react";

/** Low-resolution pixel size, in CSS pixels. */
const CELL = 4;
/** One star per this many low-resolution pixels. */
const DENSITY = 150;

/**
 * Renders the stars into a canvas pinned to the viewport, so a long page
 * never asks for a canvas taller than the browser will allocate.
 *
 * The field is seeded, so it looks the same on every visit, and is reseeded
 * only when the canvas changes size. Reduced motion holds every star still.
 *
 * @param className - Extra classes for the canvas.
 * @returns The canvas.
 */
export default function Starfield({ className = "" }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const t0 = performance.now();
    let field: { lw: number; lh: number; stars: { x: number; y: number; ph: number; b: number }[] } | null = null;
    let raf = 0;

    const frame = () => {
      raf = requestAnimationFrame(frame);
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const W = Math.round(canvas.clientWidth * dpr);
      const H = Math.round(canvas.clientHeight * dpr);
      if (!W || !H) return;
      if (canvas.width !== W || canvas.height !== H) {
        canvas.width = W;
        canvas.height = H;
      }
      const cell = Math.max(2, Math.round(CELL * dpr));
      const lw = Math.ceil(W / cell);
      const lh = Math.ceil(H / cell);
      if (!field || field.lw !== lw || field.lh !== lh) {
        let seed = 41;
        const rnd = () => {
          seed = (seed + 0x6d2b79f5) | 0;
          let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
          t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
          return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
        };
        const count = Math.round((lw * lh) / DENSITY);
        field = {
          lw,
          lh,
          stars: Array.from({ length: count }, () => ({
            x: Math.floor(rnd() * lw),
            y: Math.floor(rnd() * lh),
            ph: rnd(),
            b: rnd(),
          })),
        };
      }
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const t = reduce ? 0 : performance.now() - t0;
      ctx.clearRect(0, 0, W, H);
      for (const star of field.stars) {
        const twinkle = reduce ? 0.5 : 0.5 + 0.5 * Math.sin(t * 0.0012 + star.ph * 6.283);
        ctx.fillStyle = `rgba(250,250,250,${(0.05 + 0.12 * star.b * twinkle).toFixed(3)})`;
        ctx.fillRect(star.x * cell, star.y * cell, cell, cell);
      }
      // A still field needs drawing once, and again only when it resizes.
      if (reduce) cancelAnimationFrame(raf);
    };
    raf = requestAnimationFrame(frame);
    const redraw = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(frame);
    };
    if (reduce) window.addEventListener("resize", redraw);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", redraw);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className={`pointer-events-none fixed inset-0 block h-dvh w-full ${className}`}
    />
  );
}
