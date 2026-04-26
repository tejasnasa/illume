import { GearFineIcon, StarFourIcon } from "@phosphor-icons/react/dist/ssr";
import Skeleton from "./Skeleton";

export default function RepoNavSkel() {
  return (
    <header className="flex backdrop-blur-xs items-center justify-between sticky top-0 z-10 print:hidden">
      <section className="flex items-center">
        <div className="relative h-12 w-12 flex items-center justify-center m-2">
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="h-10 w-10 rounded-full bg-(--chart-1)/30 blur-xl" />
          </div>
          <StarFourIcon
            className="relative text-(--chart-1)"
            weight="fill"
            size={24}
          />
        </div>
        <Skeleton className="h-5 w-32 mx-2" />
      </section>

      <section className="flex items-center">
        <div className="m-2 mx-4 font-semibold">Home</div>
        <div className="m-2 mx-4 text-(--muted-foreground) animate-pulse">
          Glossary
        </div>
        <div className="m-2 mx-4 text-(--muted-foreground) animate-pulse">
          Explorer
        </div>
        <div className="m-2 mx-4 text-(--muted-foreground) animate-pulse">
          Graph
        </div>
        <GearFineIcon
          size={24}
          className="m-2 mx-4 mr-6 text-(--muted-foreground) hover:cursor-pointer animate-pulse"
        />
      </section>
    </header>
  );
}
