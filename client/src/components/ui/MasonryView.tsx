"use client";

import Repository from "@/types/repository";
import Masonry from "react-masonry-css";
import RepoCard from "./RepoCard";

export default function MasonryView({
  repositories,
}: {
  repositories: Repository[];
}) {
  return (
    <Masonry
      className="flex gap-5 mt-6"
      columnClassName="space-y-5"
      breakpointCols={2}
    >
      {repositories.map((repo) => (
        <RepoCard key={repo.id} repo={repo} />
      ))}
    </Masonry>
  );
}
