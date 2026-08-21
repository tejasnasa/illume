export default interface Repository {
  id: string;
  github_url: string;
  name: string;
  status: string;
  architecture_summary: string;
  repo_number: number;
  primary_language: string;
  detected_stack: {
    ci_cd: string[];
    databases: string[];
    languages: string[];
    frameworks: string[];
    infrastructure: string[];
  };
  entry_points: unknown;
  ingested_branch: string | null;
  ingested_commit_sha: string | null;
  created_at: Date;
  updated_at: Date;
}
