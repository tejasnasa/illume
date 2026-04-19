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
  };
  entry_points: unknown;
  created_at: Date;
  updated_at: Date;
}
