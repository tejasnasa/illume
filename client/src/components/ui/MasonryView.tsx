"use client"

import Masonry from "react-masonry-css";
import RepoCard from "./RepoCard";

interface Repository {
  id: number;
  name: string;
  description: string;
  updatedAt: string;
  github_url: string;
  status: string;
}

export default function MasonryView({
  repositories,
}: {
  repositories: Repository[];
}) {
  return (
    <Masonry
      className="flex gap-5 mt-6"
      columnClassName="space-y-5"
      breakpointCols={4}
    >
      {repositories.map((repo) => (
        <RepoCard key={repo.id} repo={repo} />
      ))}
    </Masonry>
  );
}
