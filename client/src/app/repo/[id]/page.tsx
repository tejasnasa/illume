import { GetGuide } from "@/api/guide";
import { GetRepository } from "@/api/repository";
import Chat from "@/components/Chat";
import { timeAgo } from "@/utils/timeAgo";
import { GithubLogoIcon, LinkIcon } from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";

export default async function Repository({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const repo = await GetRepository(Number(id));
  const guide = await GetGuide(repo.id);

  return (
    <main className="p-4 h-[calc(100dvh-4rem)] flex gap-4">
      <section className="flex gap-4 w-1/2 flex-col h-full">
        <div className="backdrop-blur-xs border rounded-sm p-4 overflow-scroll bg-black/30 h-1/2">
          <h2 className="text-2xl font-semibold mb-2">Architecture Summary</h2>
          <p className="text-justify whitespace-pre-line">
            {repo.architecture_summary}
          </p>
        </div>

        <div className="h-1/2 flex gap-4">
          <div className="backdrop-blur-xs border rounded-sm p-4 overflow-scroll bg-black/30 flex flex-col gap-2 w-1/2">
            <h2 className="text-2xl font-semibold mb-2 w-1/2">Tech Stack</h2>
            {repo.detected_stack.languages.length > 0 && (
              <div>
                <h3 className="text-lg font-medium">Languages</h3>
                <ul className="list-disc list-inside">
                  {repo.detected_stack.languages.map((tool, index) => (
                    <li key={index}>{tool}</li>
                  ))}
                </ul>
              </div>
            )}

            {repo.detected_stack.frameworks.length > 0 && (
              <div>
                <h3 className="text-lg font-medium">Frameworks</h3>
                <ul className="list-disc list-inside">
                  {repo.detected_stack.frameworks.map((tool, index) => (
                    <li key={index}>{tool}</li>
                  ))}
                </ul>
              </div>
            )}

            {repo.detected_stack.ci_cd.length > 0 && (
              <div>
                <h3 className="text-lg font-medium">CI/CD</h3>
                <ul className="list-disc list-inside">
                  {repo.detected_stack.ci_cd.map((tool, index) => (
                    <li key={index}>{tool}</li>
                  ))}
                </ul>
              </div>
            )}

            {repo.detected_stack.databases.length > 0 && (
              <div>
                <h3 className="text-lg font-medium">Databases</h3>
                <ul className="list-disc list-inside">
                  {repo.detected_stack.databases.map((tool, index) => (
                    <li key={index}>{tool}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          <div className="flex flex-col gap-4 w-1/2">
            <Link
              href={repo.github_url}
              target="_blank"
              className="relative backdrop-blur-xs border rounded-sm p-4 h-1/3 overflow-scroll bg-(--foreground) text-(--background) flex justify-center items-center"
            >
              <h2 className="text-4xl font-semibold mb-2 flex items-center gap-2">
                <GithubLogoIcon />
                {repo.github_url.split("github.com/")[1].split("/")[1]}
              </h2>
              <LinkIcon className="absolute top-2 right-2" size={20} />
            </Link>
            <div className="backdrop-blur-xs border rounded-sm p-4 h-1/3 overflow-scroll bg-green-500 flex flex-col gap-2 items-center justify-center">
              <h2 className="text-2xl font-semibold mb-2">
                Status: {repo.status.toUpperCase()}
              </h2>
            </div>
            <div className="backdrop-blur-xs border rounded-sm p-4 h-1/3 overflow-scroll bg-black/30 flex flex-col gap-2">
              <h2 className="text-2xl font-semibold mb-2">
                Created {timeAgo(repo.created_at)}
              </h2>
              <h2 className="text-2xl font-semibold mb-2">
                Last Updated {timeAgo(repo.updated_at)}
              </h2>
            </div>
          </div>
        </div>
      </section>

      <Chat repoId={repo.id} />
    </main>
  );
}
