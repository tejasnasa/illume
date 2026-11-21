/**
 * Client-side renderer for the docs' ```mermaid blocks. Mermaid is imported
 * dynamically after mount, so it never ships in the page's initial bundle and never
 * runs on the server. The diagram's source stays in the server-rendered HTML as a
 * `<pre>`, which is what shows while Mermaid loads and what stays if it cannot render.
 *
 * A diagram is shown fitted to the column (never enlarged past its natural size), and
 * opens full-screen at natural size, with zoom and drag-to-pan, from its Expand label
 * or by clicking it. The app ships one dark palette, so diagrams use Mermaid's dark
 * theme.
 * @module Mermaid
 */
"use client";

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";

const ZOOM_STEP = 1.25;
const ZOOM_MIN = 0.25;
const ZOOM_MAX = 4;

/** Room a fitted diagram leaves in the expanded view: its padding plus a scrollbar. */
const STAGE_GUTTER_PX = 96;

/**
 * Reads a rendered diagram's natural width from its `viewBox`.
 *
 * @param svg - Mermaid's SVG markup.
 * @returns The width in CSS pixels, or `null` when there is no `viewBox`.
 */
export function naturalWidth(svg: string): number | null {
  const match = /viewBox="\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)/.exec(svg);
  const width = match ? Number(match[1]) : NaN;
  return Number.isFinite(width) && width > 0 ? width : null;
}

/**
 * The zoom that fits a diagram's width into the viewport, never above 1.
 *
 * @param width - The diagram's natural width.
 * @param viewport - The viewport width.
 * @returns A zoom factor in `[ZOOM_MIN, 1]`.
 */
export function fitZoom(width: number, viewport: number): number {
  const fit = (viewport - STAGE_GUTTER_PX) / width;
  return Math.min(1, Math.max(ZOOM_MIN, fit));
}

/**
 * The full-screen view of one diagram: natural size scaled by a zoom the reader
 * controls, scrolled or dragged to pan.
 */
function ExpandedDiagram({
  svg,
  width,
  onClose,
}: {
  svg: string;
  width: number;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{
    x: number;
    y: number;
    left: number;
    top: number;
  } | null>(null);
  const [zoom, setZoom] = useState(() => fitZoom(width, window.innerWidth));

  // No close() on cleanup: unmounting removes the dialog, which ends the modal
  // state, while a close() would fire `close` and re-enter onClose.
  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) dialog.showModal();
  }, []);

  const zoomBy = useCallback((factor: number) => {
    setZoom((z) => Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z * factor)));
  }, []);

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "+" || event.key === "=") zoomBy(ZOOM_STEP);
    else if (event.key === "-") zoomBy(1 / ZOOM_STEP);
    else if (event.key === "0") setZoom(1);
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    const stage = stageRef.current;
    if (!stage || event.button !== 0) return;
    drag.current = {
      x: event.clientX,
      y: event.clientY,
      left: stage.scrollLeft,
      top: stage.scrollTop,
    };
    stage.setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const stage = stageRef.current;
    const start = drag.current;
    if (!stage || !start) return;
    stage.scrollLeft = start.left - (event.clientX - start.x);
    stage.scrollTop = start.top - (event.clientY - start.y);
  };

  const endDrag = () => {
    drag.current = null;
  };

  return (
    <dialog
      ref={dialogRef}
      className="docs-mermaid-dialog"
      aria-label="Diagram"
      onClose={onClose}
      onKeyDown={onKeyDown}
    >
      <div className="docs-mermaid-toolbar">
        <button
          type="button"
          onClick={() => zoomBy(1 / ZOOM_STEP)}
          aria-label="Zoom out"
        >
          −
        </button>
        <button
          type="button"
          onClick={() => setZoom(1)}
          aria-label="Actual size"
        >
          {Math.round(zoom * 100)}%
        </button>
        <button
          type="button"
          onClick={() => zoomBy(ZOOM_STEP)}
          aria-label="Zoom in"
        >
          +
        </button>
        <button
          type="button"
          onClick={() => setZoom(fitZoom(width, window.innerWidth))}
        >
          Fit
        </button>
        <button
          type="button"
          onClick={() => dialogRef.current?.close()}
          aria-label="Close"
          className="docs-mermaid-close"
        >
          ✕
        </button>
      </div>
      <div
        ref={stageRef}
        className="docs-mermaid-stage"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        <div
          className="docs-mermaid-canvas"
          style={{ width: width * zoom }}
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      </div>
    </dialog>
  );
}

/**
 * Renders one Mermaid diagram.
 *
 * @param chart - The diagram source.
 * @returns The fitted diagram, or its source while it renders or if it cannot.
 */
export function Mermaid({ chart }: { chart: string }) {
  const id = `mermaid-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const [svg, setSvg] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { default: mermaid } = await import("mermaid");
        // Labels are drawn as SVG text, which Mermaid measures exactly; HTML
        // labels pick up the page's CSS after measuring and spill out of their
        // boxes. Measuring also needs the page's real font to have loaded.
        await document.fonts.ready;
        const fontFamily = getComputedStyle(document.body).fontFamily;
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          suppressErrorRendering: true,
          theme: "dark",
          fontFamily,
          htmlLabels: false,
          // SVG labels would otherwise wrap at a fixed width, which splits long
          // identifiers such as "WorkspaceMember" mid-word.
          markdownAutoWrap: false,
          // Fixed pixel size, so the natural width is known: the card fits it
          // to the column with CSS, and the expanded view zooms from it.
          flowchart: {
            htmlLabels: false,
            useMaxWidth: false,
            wrappingWidth: 1000,
          },
          sequence: { useMaxWidth: false },
          er: { useMaxWidth: false },
        });
        const result = await mermaid.render(id, chart);
        if (!cancelled) setSvg(result.svg);
      } catch {
        document.getElementById(`d${id}`)?.remove();
        if (!cancelled) setSvg(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [chart, id]);

  if (svg === null) {
    return (
      <pre className="docs-mermaid-fallback" data-language="mermaid">
        <code>{chart}</code>
      </pre>
    );
  }

  const width = naturalWidth(svg);

  if (width === null) {
    return (
      <div
        className="docs-mermaid"
        role="img"
        aria-label="Diagram"
        dangerouslySetInnerHTML={{ __html: svg }}
      />
    );
  }

  return (
    <div className="docs-mermaid">
      <button
        type="button"
        className="docs-mermaid-fit"
        onClick={() => setExpanded(true)}
        aria-label="Diagram. Expand to zoom"
      >
        <span dangerouslySetInnerHTML={{ __html: svg }} />
        <span className="docs-mermaid-expand" aria-hidden>
          Expand
        </span>
      </button>
      {expanded && (
        <ExpandedDiagram
          svg={svg}
          width={width}
          onClose={() => setExpanded(false)}
        />
      )}
    </div>
  );
}
