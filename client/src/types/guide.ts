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
  architecture_brief: {
    entry_points: string[];
    // Free-form LLM section; shape varies per repository.
    directory_summary: unknown;
    external_integrations: string[];
    data_flow: {
      from: string;
      to: string;
      step: number;
    }[];
    module_edges: {
      to: string;
      from: string;
    }[];
    key_modules: {
      path: string;
      fan_in: number;
      fan_out: number;
      language: string;
      criticality: string;
    }[];
    ownership_summary: {
      file_id: string;
      bus_factor: number;
      primary_owner: string;
      is_knowledge_silo: boolean;
    };
  };
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
