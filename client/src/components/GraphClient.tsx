"use client";

import Graph from "@/types/graph";
import { GraphIcon, WarningDiamondIcon } from "@phosphor-icons/react/dist/ssr";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useState } from "react";
import GraphCard from "./ui/GraphCard";

const ForceGraph3D = dynamic(() => import("react-force-graph-3d"), {
  ssr: false,
});

export default function GraphClient({
  graphData,
  currentLevel,
  repoId,
  github_url,
}: {
  graphData: Graph | null;
  currentLevel: string;
  repoId: string;
  github_url: string;
}) {
  const router = useRouter();
  const [selectedNode, setSelectedNode] = useState<any>(null);

  if (!graphData) {
    return (
      <div className="absolute inset-0 z-0 flex flex-col items-center justify-center p-6 text-center">
        <WarningDiamondIcon size={48} className="text-(--destructive) mb-4" />
        <p className="text-lg font-medium text-(--destructive)">
          Failed to load graph data
        </p>
      </div>
    );
  }

  return (
    <main className="backdrop-blur-xs bg-black/80 relative w-full h-[calc(100vh-64px)] flex flex-col items-center justify-center overflow-hidden">
      <div className="absolute bottom-4 left-4 z-10 p-2 rounded-sm flex flex-col gap-2">
        <div className="flex items-center gap-3 mb-2 text-(--primary)">
          <GraphIcon size={28} weight="duotone" />
          <h1 className="text-3xl font-bold text-(--foreground) tracking-tight">
            Graph Analyzer
          </h1>
        </div>
      </div>

      <section
        className={`absolute top-4 right-4 z-10 glass-card p-4 rounded-sm text-xs space-y-2 w-48 transition-all duration-300 ${selectedNode ? "opacity-0 pointer-events-none translate-x-10" : "opacity-100"}`}
      >
        <h4 className="font-semibold text-(--foreground) mb-2 text-sm">
          Legend
        </h4>
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-red-500"></span> Critical
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-yellow-400"></span>{" "}
          Caution
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-green-500"></span> Safe
        </div>
        <div className="flex items-center gap-2 mt-2 pt-2 border-t border-(--border)">
          Size ∝ LOC
        </div>
      </section>

      <section className="glass-card p-1 rounded-sm items-center justify-between flex absolute top-4 left-4 z-10">
        <button
          onClick={() => {
            setSelectedNode(null);
            router.push(`/repo/${repoId}/graph?level=file`);
          }}
          className={`px-5 py-1.5 rounded-xs text-sm transition-colors ${
            currentLevel === "file"
              ? "bg-(--primary) text-white"
              : "hover:bg-(--primary)/10 text-(--muted-foreground)"
          }`}
        >
          File Level
        </button>
        <button
          onClick={() => {
            setSelectedNode(null);
            router.push(`/repo/${repoId}/graph?level=symbol`);
          }}
          className={`px-5 py-1.5 rounded-xs text-sm transition-colors ${
            currentLevel === "symbol"
              ? "bg-(--primary) text-white"
              : "hover:bg-(--primary)/10 text-(--muted-foreground)"
          }`}
        >
          Symbol Level
        </button>
      </section>

      {selectedNode && (
        <GraphCard
          selectedNode={selectedNode}
          setSelectedNode={setSelectedNode}
          currentLevel={currentLevel}
          github_url={github_url}
        />
      )}

      <section className="w-full h-full cursor-move">
        <ForceGraph3D
          graphData={graphData as any}
          nodeLabel={(node: any) =>
            `${node.label} (${node.criticality || "safe"})`
          }
          nodeVal={(node: any) => Math.sqrt(node.loc || 10) * 0.5}
          nodeColor={(node: any) => {
            if (node.id === selectedNode?.id) return "#0078ff";
            if (node.criticality === "critical") return "#ef4444";
            if (node.criticality === "caution") return "#facc15";
            return "#22c55e";
          }}
          linkWidth={(link: any) => {
            if (!selectedNode) return 1;
            return link.source?.id === selectedNode?.id ||
              link.target?.id === selectedNode?.id
              ? 2
              : 1;
          }}
          linkColor={(link: any) => {
            if (!selectedNode) return "rgba(255,255,255,0.3)";
            return link.source?.id === selectedNode?.id ||
              link.target?.id === selectedNode?.id
              ? "rgba(0,120,255,0.7)"
              : "rgba(255,255,255,0.3)";
          }}
          backgroundColor="#00000000"
          linkDirectionalParticles={1}
          linkDirectionalParticleSpeed={0.005}
          nodeOpacity={0.9}
          linkOpacity={1}
          onNodeClick={(node) => setSelectedNode(node)}
          onBackgroundClick={() => setSelectedNode(null)}
        />
      </section>
    </main>
  );
}
