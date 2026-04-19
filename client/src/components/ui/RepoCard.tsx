import Repository from "@/types/repository";
import { timeAgo } from "@/utils/timeAgo";
import { GithubLogoIcon } from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";

interface RepoCardProps {
  repo: Repository;
}

export default function RepoCard({ repo }: RepoCardProps) {
  return (
    <Link
      href={`/repo/${repo.repo_number}`}
      className="bg-(--card) border rounded-sm p-4 block"
    >
      <h3 className="text-2xl">{repo.name}</h3>
      <GithubLogoIcon />
      <p className="text-sm text-(--muted-foreground)">
        {repo.architecture_summary}
      </p>
      <p className="text-xs text-(--muted-foreground)">
        {timeAgo(repo.updated_at)}
      </p>
      <p className="text-xs">status: {repo.status}</p>
    </Link>
  );
}
