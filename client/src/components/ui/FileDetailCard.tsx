import { FileNode } from "@/types/explorer";
import {
  CrownIcon,
  FileTextIcon,
  GithubLogoIcon,
  UserCircleIcon,
  WarningDiamondIcon,
  XIcon,
} from "@phosphor-icons/react/dist/ssr";
import { motion } from "motion/react";
import Link from "next/link";

interface Props {
  file: FileNode;
  ownershipData: any;
  isLoading: boolean;
  githubUrl: string;
  annotation: string | null;
  onClose: () => void;
}

export default function FileDetailCard({
  file,
  ownershipData,
  isLoading,
  githubUrl,
  onClose,
  annotation,
}: Props) {
  return (
    <motion.div
      key="detail-card"
      initial={{ x: "100%", opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      exit={{ x: "100%", opacity: 0 }}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
      className="flex-1 min-w-0 sticky top-18"
    >
      <div className="glass-card p-5 rounded-sm border border-(--border) bg-(--card)/60 backdrop-blur-xl shadow-2xl relative overflow-hidden">
        <div className="absolute top-0 left-0 w-full h-1 bg-linear-to-r from-(--primary) to-(--chart-2)" />

        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-2 hover:bg-(--secondary) hover:cursor-pointer rounded-full transition-colors text-(--muted-foreground)"
        >
          <XIcon size={20} />
        </button>

        <Link
          href={`${githubUrl}/blob/master/${file.path}`}
          target="_blank"
          className="absolute p-2 top-4 right-14 text-(--muted-foreground) hover:bg-(--secondary) rounded-full transition-colors"
        >
          <GithubLogoIcon size={20} />
        </Link>

        <div className="mb-4 pb-4 border-b border-(--border)">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-8 h-8 rounded-sm bg-(--primary)/10 flex items-center justify-center text-(--primary)">
              <FileTextIcon size={20} weight="duotone" />
            </div>
            <h2 className="font-bold text-xl text-(--foreground) truncate pr-8">
              {file.label}
            </h2>
          </div>

          <div className="flex flex-wrap gap-2 mb-3">
            <span className="px-2.5 py-1 rounded-sm text-[10px] font-bold tracking-wider uppercase bg-(--secondary) text-(--muted-foreground) border border-(--border)">
              {file.language || "Unknown"}
            </span>
            <span
              className={`px-2.5 py-1 rounded-sm text-[10px] font-bold tracking-wider uppercase border ${
                file.criticality === "critical"
                  ? "bg-red-500/10 text-red-500 border-red-500/20"
                  : "bg-green-500/10 text-green-500 border-green-500/20"
              }`}
            >
              {file.criticality}
            </span>
            {ownershipData?.is_knowledge_silo && (
              <span className="px-2.5 py-1 rounded-sm text-[10px] font-bold tracking-wider uppercase bg-amber-500/10 text-amber-500 border border-amber-500/20">
                Knowledge Silo
              </span>
            )}
          </div>

          <div className="text-xs text-(--muted-foreground) break-all font-mono bg-(--secondary)/30 p-2 rounded-sm border border-(--border)/50">
            {file.path}
          </div>
        </div>

        {isLoading ? (
          <div className="py-12 flex flex-col items-center justify-center gap-4">
            <div className="w-10 h-10 border-4 border-(--primary)/30 border-t-(--primary) rounded-full animate-spin" />
            <p className="text-sm text-(--muted-foreground) animate-pulse">
              Loading ownership data...
            </p>
          </div>
        ) : ownershipData ? (
          <div className="space-y-6">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-(--muted-foreground) font-semibold mb-3">
                Primary Owner
              </div>
              <div className="flex items-center gap-3 p-3 rounded-lg bg-(--primary)/5 border border-(--primary)/10 hover:bg-(--primary)/10 transition-colors">
                <div className="w-10 h-10 rounded-full bg-amber-400/20 flex items-center justify-center text-amber-400">
                  <CrownIcon size={24} weight="duotone" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-semibold text-(--foreground) truncate">
                    {ownershipData.primary_owner || "Unknown"}
                  </div>
                  <div className="text-[10px] text-(--muted-foreground)">
                    Highest contribution share
                  </div>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="bg-(--secondary)/40 rounded-sm p-4 border border-(--border) hover:border-(--primary)/30 transition-colors">
                <span className="block text-[10px] text-(--muted-foreground) uppercase mb-1 font-semibold">
                  Bus Factor
                </span>
                <div className="flex items-end gap-2">
                  <span
                    className={`text-2xl font-bold ${ownershipData.bus_factor === 1 ? "text-red-500" : "text-(--foreground)"}`}
                  >
                    {ownershipData.bus_factor}
                  </span>
                  <span className="text-[10px] text-(--muted-foreground) mb-1.5 font-medium">
                    {ownershipData.bus_factor === 1 ? "engineer" : "engineers"}
                  </span>
                </div>
              </div>
              <div className="bg-(--secondary)/40 rounded-sm p-4 border border-(--border) hover:border-(--primary)/30 transition-colors">
                <span className="block text-[10px] text-(--muted-foreground) uppercase mb-1 font-semibold">
                  Contributors
                </span>
                <div className="flex items-end gap-2">
                  <span className="text-2xl font-bold text-(--foreground)">
                    {ownershipData.contributors.length}
                  </span>
                  <span className="text-[10px] text-(--muted-foreground) mb-1.5 font-medium">
                    total
                  </span>
                </div>
              </div>
            </div>

            {ownershipData.contributors.length > 0 && (
              <div>
                <div className="flex justify-between items-center mb-3">
                  <span className="text-[10px] uppercase tracking-wider text-(--muted-foreground) font-semibold">
                    Knowledge Distribution
                  </span>
                  <span className="text-[10px] text-(--muted-foreground)">
                    {ownershipData.contributors.length} authors
                  </span>
                </div>
                <div className="space-y-2 max-h-60 overflow-y-auto pr-2 custom-scrollbar">
                  {ownershipData.contributors.map((c: any, idx: number) => (
                    <div key={idx} className="flex flex-col gap-1.5">
                      <div className="flex justify-between items-center text-xs">
                        <div className="flex items-center gap-2 overflow-hidden">
                          <div className="w-5 h-5 rounded-full bg-(--secondary) flex items-center justify-center text-(--muted-foreground)">
                            <UserCircleIcon size={14} />
                          </div>
                          <span
                            className="truncate text-(--foreground) font-medium"
                            title={c.name}
                          >
                            {c.name}
                          </span>
                        </div>
                        <span className="font-mono text-(--primary) font-bold">
                          {c.percentage ? `${c.percentage.toFixed(1)}%` : "N/A"}
                        </span>
                      </div>
                      <div className="w-full h-1 bg-(--secondary) rounded-full overflow-hidden">
                        <motion.div
                          initial={{ width: 0 }}
                          animate={{ width: `${c.percentage || 0}%` }}
                          transition={{
                            duration: 1,
                            ease: "easeOut",
                            delay: idx * 0.1,
                          }}
                          className="h-full bg-(--primary)"
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {annotation && (
              <div className="mt-4 pt-4 border-t border-(--border)">
                <p className="text-sm text-(--muted-foreground)">
                  Note: {annotation}
                </p>
              </div>
            )}
          </div>
        ) : (
          <div className="py-12 flex flex-col items-center justify-center gap-4 text-center">
            <WarningDiamondIcon
              size={48}
              weight="duotone"
              className="text-amber-500/50"
            />
            <div>
              <p className="text-(--foreground) font-medium">
                No ownership data
              </p>
              <p className="text-xs text-(--muted-foreground) max-w-50 mx-auto mt-1">
                This file might not have enough history or is untracked.
              </p>
            </div>
          </div>
        )}
      </div>
    </motion.div>
  );
}
