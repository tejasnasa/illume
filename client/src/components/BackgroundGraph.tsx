"use client";

import data from "@/data/graph.json";
import { useEffect, useRef } from "react";
import ForceGraph3D from "react-force-graph-3d";

const ORBIT_SPEED = 0.0001; // radians per ms

export default function BackgroundGraph() {
  const fgRef = useRef<any>(null);
  const angleRef = useRef(0);
  const rafRef = useRef<number | null>(null);
  const lastTimeRef = useRef<number | null>(null);

  useEffect(() => {
    if (!fgRef.current) return;

    fgRef.current.d3Force("link").distance(200);
    fgRef.current.d3Force("charge").strength(-300);

    fgRef.current.d3ReheatSimulation?.();
    fgRef.current.d3AlphaDecay?.(0.005);
    fgRef.current.d3VelocityDecay?.(0.6);

    const initialCam = fgRef.current.cameraPosition();
    const radius = Math.sqrt(initialCam.x ** 2 + initialCam.z ** 2) || 600;

    const animate = (timestamp: number) => {
      if (lastTimeRef.current !== null) {
        const delta = timestamp - lastTimeRef.current;
        angleRef.current += ORBIT_SPEED * delta;
      }
      lastTimeRef.current = timestamp;

      fgRef.current?.cameraPosition({
        x: radius * Math.sin(angleRef.current),
        y: initialCam.y,
        z: radius * Math.cos(angleRef.current),
      });

      rafRef.current = requestAnimationFrame(animate);
    };

    rafRef.current = requestAnimationFrame(animate);

    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  return (
    <div className="fixed inset-0 -z-10">
      <ForceGraph3D
        graphData={data}
        nodeLabel="label"
        nodeVal={(node: any) => node.loc || 10}
        linkDirectionalParticles={2}
        linkDirectionalParticleSpeed={0.005}
        backgroundColor="#00000000"
        nodeColor={() => "rgb(59, 130, 246)"}
        ref={fgRef}
        enableNodeDrag={false}
        enableNavigationControls={false}
        enablePointerInteraction={false}
      />
    </div>
  );
}
