import Skeleton from "@/components/ui/Skeleton";
import { FolderOpenIcon } from "@phosphor-icons/react/dist/ssr";

export default function ExplorerLoading() {
  return (
    <main className="max-w-4xl mx-auto pt-12 text-(--muted-foreground) overflow-hidden h-[calc(100vh-64px)] animate-pulse">
      <div className="flex gap-3 mb-2 justify-between flex-col">
        <div className="flex justify-between items-end gap-3 mb-2 ">
          <div className="flex gap-3 items-center ">
            <FolderOpenIcon size={28} weight="duotone" />
            <h1 className="text-3xl font-bold  tracking-tight">
              File Explorer
            </h1>
          </div>

          <div className="flex justify-between items-center mb-6 gap-4">
            <Skeleton className="w-32 h-7 rounded-md" />
            <div className="flex items-center gap-2">
              <Skeleton className="w-7 h-7 rounded-md" />
              <Skeleton className="w-12 h-7 rounded-md" />
              <Skeleton className="w-7 h-7 rounded-md" />
            </div>
          </div>
        </div>

        <p className="text-(--muted-foreground)">
          Browse the entire repository tree. Criticality guardrails are mapped
          directly to files.
        </p>
      </div>

      <div className="glass-card rounded-sm overflow-hidden border border-(--border) bg-(--card)/40 p-2">
        <div className="flex items-center justify-between px-4 py-3 bg-(--secondary)/40 rounded-xs mb-2 border border-(--border)">
          <span className="text-xs font-semibold uppercase tracking-wider text-(--muted-foreground)">
            Directory / File
          </span>
          <div className="flex items-center gap-8 text-xs font-semibold uppercase tracking-wider text-(--muted-foreground)">
            <span className="w-16 text-right">LOC</span>
            <span className="w-24 text-right">Guardrail</span>
          </div>
        </div>

        <div className="p-4">
          <div className="min-w-150 flex flex-col gap-2 overflow-hidden">
            <Skeleton className="w-full h-7 rounded-md shrink-0" />
            <Skeleton className="w-full h-7 rounded-md shrink-0" />
            <Skeleton className="w-full h-7 rounded-md shrink-0" />
            <Skeleton className="w-full h-7 rounded-md shrink-0" />
            <Skeleton className="w-full h-7 rounded-md shrink-0" />
            <Skeleton className="w-full h-7 rounded-md shrink-0" />
            <Skeleton className="w-full h-7 rounded-md shrink-0" />
            <Skeleton className="w-full h-7 rounded-md shrink-0" />
          </div>
        </div>
      </div>
    </main>
  );
}
