/**
 * A frame counter for the landing page's scripted demos.
 * @module useTicker
 */
"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Counts up once per `intervalMs` while the observed element is on screen.
 *
 * Every demo on the landing page is a pure function of this counter, so the
 * same tick always draws the same frame. The counter pauses while the element
 * is scrolled out of view, so a long page does not run a dozen timers at once,
 * and it never starts for a visitor who has asked for reduced motion: they get
 * `finalTick`, the demo's finished state, instead of an animation.
 *
 * @param intervalMs Milliseconds per tick.
 * @param finalTick The tick to show when motion is reduced.
 * @returns A ref to attach to the demo's root and the current tick.
 */
export function useTicker<T extends HTMLElement = HTMLDivElement>(
  intervalMs = 100,
  finalTick = 0,
): [React.RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [tick, setTick] = useState(0);
  const [visible, setVisible] = useState(false);
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!media) return;
    const sync = () => setReduced(media.matches);
    sync();
    media.addEventListener?.("change", sync);
    return () => media.removeEventListener?.("change", sync);
  }, []);

  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => setVisible(entry.isIntersecting),
      { rootMargin: "120px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!visible || reduced) return;
    const timer = window.setInterval(() => setTick((t) => t + 1), intervalMs);
    return () => window.clearInterval(timer);
  }, [visible, reduced, intervalMs]);

  return [ref, reduced ? finalTick : tick];
}

/**
 * The prefix of `text` revealed `perTick` characters at a time.
 *
 * @param text The full string.
 * @param tick Ticks elapsed since typing began.
 * @param perTick Characters typed per tick.
 * @returns The typed prefix.
 */
export function typed(text: string, tick: number, perTick = 2): string {
  return text.slice(0, Math.max(0, Math.min(text.length, tick * perTick)));
}
