import deleteRepoAction from "@/actions/deleteRepo";
import regenerateRepoAction from "@/actions/regenerateRepo";
import {
  GearFineIcon,
  RepeatIcon,
  TrashIcon,
} from "@phosphor-icons/react/dist/ssr";
import Button from "./ui/Button";
import Modal from "./ui/Modal";

export default function RepoSettings({ repo_id }: { repo_id: string }) {
  return (
    <div className="p-4">
      <div className="flex items-center gap-3 mb-6 text-(--primary)">
        <GearFineIcon size={28} weight="duotone" />
        <h1 className="text-3xl font-bold text-(--foreground) tracking-tight">
          Settings
        </h1>
      </div>

      <div className="mt-8 rounded-sm border border-red-500/20 divide-y divide-red-500/10 w-125">
        <div className="px-5 py-3">
          <p className="text-xs font-semibold uppercase tracking-widest text-red-400">
            Danger Zone
          </p>
        </div>

        <div className="flex items-center justify-between px-5 py-4">
          <div>
            <p className="text-sm font-medium text-(--foreground)">
              Delete Repository
            </p>
            <p className="text-xs text-(--muted-foreground) mt-0.5">
              Permanently remove this repository and all its data.
            </p>
          </div>
          <Modal
            className="p-4 w-120"
            trigger={
              <Button
                size="sm"
                className="border-red-500/40 bg-white text-red-500 hover:border-red-500/60 gap-1.5 shrink-0"
              >
                <TrashIcon weight="duotone" size={15} />
                Delete
              </Button>
            }
          >
            <div className="flex items-center gap-3 mb-1 text-red-400 text-2xl">
              <TrashIcon weight="duotone" />
              <h1 className="font-bold text-(--foreground) tracking-tight">
                Delete Repository
              </h1>
            </div>
            <p className="text-(--muted-foreground) mb-12 text-sm">
              Are you sure you want to delete this repository?
            </p>
            <Button
              onClick={() => deleteRepoAction(repo_id)}
              size="sm"
              className="font-semibold absolute bottom-4 right-4 bg-red-500 hover:bg-red-600 text-white border-none"
            >
              DELETE
            </Button>
          </Modal>
        </div>

        <div className="flex items-center justify-between px-5 py-4">
          <div>
            <p className="text-sm font-medium text-(--foreground)">
              Regenerate Repository
            </p>
            <p className="text-xs text-(--muted-foreground) mt-0.5">
              Re-analyze and rebuild all repository insights.
            </p>
          </div>
          <Modal
            className="p-4 w-120"
            trigger={
              <Button size="sm" className="gap-1.5 shrink-0">
                <RepeatIcon weight="duotone" size={15} />
                Regenerate
              </Button>
            }
          >
            <div className="flex items-center gap-3 mb-1 text-(--primary) text-2xl">
              <RepeatIcon weight="duotone" />
              <h1 className="font-bold text-(--foreground) tracking-tight">
                Regenerate Repository
              </h1>
            </div>
            <p className="text-(--muted-foreground) mb-12 text-sm">
              Are you sure you want to regenerate this repository?
            </p>
            <Button
              onClick={() => regenerateRepoAction(repo_id)}
              size="sm"
              className="font-semibold absolute bottom-4 right-4"
            >
              REGENERATE
            </Button>
          </Modal>
        </div>
      </div>
    </div>
  );
}
