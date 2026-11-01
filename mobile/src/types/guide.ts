/**
 * Onboarding guide and repository stats response shapes.
 * @module GuideTypes
 */

/**
 * Full onboarding guide: reading order, critical files, and architecture brief.
 */
export default interface Guide {
  repository_id: string;
  reading_order: {
    position: number;
    file_path: string;
    annotation: string;
    fan_in: number;
  }[];
  critical_files: {
    file_path: string;
    criticality: string;
    reasons: string[];
    fan_in: number;
    change_frequency: number;
    has_tests: boolean;
  }[];
  /**
   * Every section is optional on the server: the brief is produced by an
   * LLM and degrades to the sections it managed to generate, so a keyless
   * or partially-failed run sends ``null`` for the rest.
   */
  architecture_brief: {
    entry_points: string[] | null;
    // Free-form LLM section; shape varies per repository.
    directory_summary: unknown;
    external_integrations: string[] | null;
    data_flow: {
      from: string;
      to: string;
      step: number | null;
    }[] | null;
    module_edges: {
      to: string;
      from: string;
    }[] | null;
    key_modules: {
      path: string;
      fan_in: number;
      fan_out: number;
      language: string;
      criticality: string;
    }[] | null;
    ownership_summary: {
      file_id: string;
      bus_factor: number;
      primary_owner: string | null;
      is_knowledge_silo: boolean;
    }[] | null;
  } | null;
}

/**
 * Aggregated repository statistics for dashboard display.
 */
export interface Stats {
  repository_id: string;
  total_files: number;
  total_loc: number;
  language_breakdown: {
    language: string;
    file_count: number;
    loc_count: number;
  }[];
  total_contributors: number;
  top_contributors: {
    name: string;
    files_owned: string;
  }[];
  knowledge_silo_count: number;
  total_dependencies: number;
}
