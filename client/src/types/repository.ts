/**
 * Repository record with analysis status and detected metadata.
 * @module RepositoryTypes
 */

/**
 * Ingested repository as returned by the repository endpoints.
 */
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
  // Shape varies by stack (map or list of entry-point candidates).
  entry_points: unknown;
  ingested_branch: string | null;
  ingested_commit_sha: string | null;
  analysis_commit_sha: string | null;
  created_at: Date;
  updated_at: Date;
  auto_update_enabled: boolean;
  auto_update_interval_hours: number;
  next_sync_at: Date | null;
  last_synced_at: Date | null;
  sync_status: string;
  last_sync_error: string | null;
  consecutive_sync_failures: number;
  last_sync_summary: unknown;
}
