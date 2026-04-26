import {
  CodeIcon,
  FileCodeIcon,
  GithubLogoIcon,
  XIcon,
} from "@phosphor-icons/react/dist/ssr";

export default function GraphCard({
  selectedNode,
  setSelectedNode,
  currentLevel,
  github_url,
  annotation,
}: {
  selectedNode: any;
  setSelectedNode: (node: any) => void;
  currentLevel: string;
  github_url: string;
  annotation: string | null;
}) {
  return (
    <section className="absolute top-4 right-4 z-20 w-80 glass-card p-5 rounded-sm flex flex-col shadow-2xl animate-fade-left h-fit">
      <div className="absolute top-0 left-0 w-full h-1 bg-linear-to-r from-(--primary) to-(--chart-2)" />
      <button
        onClick={() => setSelectedNode(null)}
        className="absolute top-4 right-4 p-2 rounded-full cursor-pointer text-(--muted-foreground) hover:text-(--foreground) hover:bg-(--secondary) transition-colors"
      >
        <XIcon size={16} weight="bold" />
      </button>

      <div className="text-xl font-bold text-(--foreground) mb-2 break-all pr-6 leading-tight flex items-center gap-2">
        {currentLevel === "file" && (
          <div className="w-8 h-8 rounded-sm bg-(--primary)/10 flex items-center justify-center text-(--primary)">
            <FileCodeIcon size={20} weight="duotone" />
          </div>
        )}
        {currentLevel === "symbol" && (
          <div className="w-8 h-8 rounded-sm bg-(--primary)/10 flex items-center justify-center text-(--primary)">
            <CodeIcon size={20} weight="duotone" />
          </div>
        )}
        <h2 className="font-bold text-xl text-(--foreground) truncate pr-8">
          {selectedNode.label}
        </h2>
      </div>

      <div className="flex items-center gap-2 mb-6">
        <span className="px-2.5 py-1 rounded-sm text-[10px] uppercase font-bold tracking-widest bg-(--secondary) text-(--foreground) border border-(--border)">
          {selectedNode.kind || currentLevel}
        </span>
        {selectedNode.criticality && (
          <span
            className={`px-2.5 py-1 rounded-sm text-[10px] font-bold tracking-wider uppercase border ${
              selectedNode.criticality === "critical"
                ? "bg-red-500/10 text-red-500 border-red-500/20"
                : "bg-green-500/10 text-green-500 border-green-500/20"
            }`}
          >
            {selectedNode.criticality}
          </span>
        )}
      </div>

      <div className="space-y-4 flex-1 overflow-y-auto custom-scrollbar">
        <label
          htmlFor="full-path"
          className="text-xs text-(--muted-foreground)"
        >
          Full Path
        </label>
        <div className="text-sm text-(--muted-foreground) break-all font-mono bg-(--secondary)/30 p-2 rounded-sm border border-(--border)/50">
          {selectedNode.path}
        </div>

        {selectedNode.group && (
          <div>
            <span className="text-xs text-(--muted-foreground) block mb-1">
              Directory Group
            </span>
            <p className="text-sm text-(--foreground)">{selectedNode.group}</p>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 pt-2">
          <div className="bg-(--secondary)/30 p-3 rounded-sm border border-(--border)">
            <span className="text-[10px] uppercase tracking-wider text-(--muted-foreground) block mb-1">
              Lines of Code
            </span>
            <p className="font-mono text-lg font-semibold">
              {selectedNode.loc || 0}
            </p>
          </div>

          {selectedNode.language && (
            <div className="bg-(--secondary)/30 p-3 rounded-sm border border-(--border)">
              <span className="text-[10px] uppercase tracking-wider text-(--muted-foreground) block mb-1">
                Language
              </span>
              <p className="font-mono text-sm font-semibold truncate mt-1.5">
                {selectedNode.language}
              </p>
            </div>
          )}

          {currentLevel === "file" && (
            <>
              <div className="bg-(--secondary)/30 p-3 rounded-sm border border-(--border)">
                <span className="text-[10px] uppercase tracking-wider text-(--muted-foreground) block mb-1">
                  Fan In
                </span>
                <p className="font-mono text-lg font-semibold">
                  {selectedNode.fan_in || 0}
                </p>
              </div>
              <div className="bg-(--secondary)/30 p-3 rounded-sm border border-(--border)">
                <span className="text-[10px] uppercase tracking-wider text-(--muted-foreground) block mb-1">
                  Fan Out
                </span>
                <p className="font-mono text-lg font-semibold">
                  {selectedNode.fan_out || 0}
                </p>
              </div>
            </>
          )}

          {currentLevel === "symbol" &&
            typeof selectedNode.complexity !== "undefined" && (
              <div className="bg-(--secondary)/30 p-3 rounded-sm border border-(--border) col-span-1">
                <span className="text-[10px] uppercase tracking-wider text-(--muted-foreground) block mb-1">
                  Cyclomatic Complexity
                </span>
                <p className="font-mono text-lg font-semibold">
                  {selectedNode.complexity}
                </p>
              </div>
            )}
        </div>

        {annotation && (
          <div className="mt-4 pt-4 border-t border-(--border)">
            <p className="text-sm text-(--muted-foreground)">Note: {annotation}</p>
          </div>
        )}

        <a
          className="bg-white hover:bg-white/80 transition-colors text-black flex items-center gap-2 p-2 justify-center rounded-sm font-semibold uppercase"
          href={`${github_url}/blob/master/${selectedNode.path}`}
          target="_blank"
        >
          <GithubLogoIcon weight="bold" />
          Github
        </a>
      </div>
    </section>
  );
}
