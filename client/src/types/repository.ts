export default interface Repository {
  id: number;
  github_url: string;
  name: string;
  status: string;
  architecture_summary: string;
  repo_number: number;
  primary_language: string;
  detected_stack: unknown;
  entry_points: unknown;
  created_at: Date;
  updated_at: Date;
}
