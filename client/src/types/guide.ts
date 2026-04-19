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
    detected_stack: unknown;
    entry_points: unknown;
    directory_summary: unknown;
    external_integrations: string[];
    data_flow: {
      from: string;
      to: string;
      step: number;
    }[];
    summary: string;
  };
}
