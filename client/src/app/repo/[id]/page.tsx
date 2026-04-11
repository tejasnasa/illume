"use client";

import data from "@/data/graph.json";
import { useEffect, useRef } from "react";
import ForceGraph3D from "react-force-graph-3d";

export default function Repository() {
  const fgRef = useRef<any>(null);

  useEffect(() => {
    if (!fgRef.current) return;

    // increase edge length
    fgRef.current.d3Force("link").distance(200);

    // increase spacing (repulsion)
    fgRef.current.d3Force("charge").strength(-300);
  }, []);
  return (
    <main>
      <ForceGraph3D
        graphData={data}
        nodeLabel="label"
        nodeAutoColorBy="group"
        nodeVal={(node: any) => node.loc || 10}
        linkDirectionalParticles={2}
        linkDirectionalParticleSpeed={0.005}
        backgroundColor="#00000000"
        ref={fgRef}
      />
    </main>
  );
}
