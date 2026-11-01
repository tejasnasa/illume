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
  // Null until the analysis has produced them (and permanently for a
  // repository whose ingest failed), so every read has to tolerate a miss.
  architecture_summary: string | null;
  repo_number: number;
  primary_language: string | null;
  detected_stack: {
    ci_cd: string[];
    databases: string[];
    languages: string[];
    frameworks: string[];
    infrastructure: string[];
  } | null;
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
  sync_available: boolean;
}
