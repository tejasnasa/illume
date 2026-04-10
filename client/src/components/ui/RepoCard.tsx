import { GithubLogoIcon } from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";

interface RepoCardProps {
  repo: {
    id: number;
    name: string;
    description: string;
    updatedAt: string;
    github_url: string;
    status: string;
  };
}

export default function RepoCard({ repo }: RepoCardProps) {
  return (
    <Link
      href={`/repo/${repo.id}`}
      className="bg-(--card) border rounded-sm p-4 block"
    >
      <h3 className="text-2xl">{repo.name}</h3>
      <GithubLogoIcon />
      <p className="text-sm text-(--muted-foreground)">{repo.description}</p>
      <p className="text-xs text-(--muted-foreground)">{repo.updatedAt}</p>
      <p className="text-xs">status: {repo.status}</p>
    </Link>
  );
}
