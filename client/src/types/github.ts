export interface GitHubRepo {
  full_name: string;
  name: string;
  private: boolean;
  default_branch: string;
  description: string | null;
  language: string | null;
  updated_at: string;
  html_url: string;
  stargazers_count: number;
}

export interface GitHubBranch {
  name: string;
  sha: string;
  is_default: boolean;
}

export interface GitHubCommit {
  sha: string;
  short_sha: string;
  message: string;
  author_name: string;
  author_avatar: string | null;
  authored_at: string;
}

export interface GitHubMultiBranchCommit extends GitHubCommit {
  parents: string[];
  branches: string[];
}
