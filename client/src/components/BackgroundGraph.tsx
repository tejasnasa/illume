"use client";
import Graph from "@/types/graph";
import dynamic from "next/dynamic";
import { useEffect, useRef } from "react";

const ForceGraph3D = dynamic(() => import("react-force-graph-3d"), {
  ssr: false,
});

const ORBIT_SPEED = 0.002; // radians per frame

export default function BackgroundGraph({ graph }: { graph: Graph | null }) {
  const fgRef = useRef<any>(null);
  const angleRef = useRef(0);
  const forcesSet = useRef(false);

  useEffect(() => {
    let rafId: number;

    const spin = () => {
      const fg = fgRef.current;
      if (fg) {
        const { x, y, z } = fg.cameraPosition();
        const r = Math.sqrt(x * x + z * z);
        angleRef.current += ORBIT_SPEED;
        fg.cameraPosition({
          x: r * Math.sin(angleRef.current),
          y,
          z: r * Math.cos(angleRef.current),
        });
      }
      rafId = requestAnimationFrame(spin);
    };

    rafId = requestAnimationFrame(spin);
    return () => cancelAnimationFrame(rafId);
  }, []);

  if (!graph) return null;

  return (
    <div className="fixed inset-0 -z-10">
      <ForceGraph3D
        ref={fgRef}
        graphData={graph}
        nodeLabel="label"
        nodeVal={(node: any) => node.loc || 10}
        linkDirectionalParticles={2}
        linkDirectionalParticleSpeed={0.005}
        linkWidth={0.5}
        backgroundColor="#00000000"
        nodeColor={() => "rgb(59, 130, 246)"}
        enableNodeDrag={false}
        enableNavigationControls={false}
        enablePointerInteraction={false}
        showNavInfo={false}
        onEngineTick={() => {
          if (forcesSet.current) return;
          const fg = fgRef.current;
          if (!fg) return;
          fg.d3Force("charge")?.strength(-250);
          fg.d3Force("link")?.distance(200);
          fg.d3ReheatSimulation();
          forcesSet.current = true;
        }}
      />
    </div>
  );
}
