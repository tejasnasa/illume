/**
 * Code ownership map and knowledge-silo response shapes.
 * @module OwnershipTypes
 */

/**
 * Paginated per-file ownership entries with total count.
 */
export default interface Ownership {
  files: {
    file_id: string;
    file_path: string;
    primary_owner: string;
    contributors: {
      name: string;
      email: string;
      percentage: number;
      last_commit: string;
    }[];
    bus_factor: number;
    is_knowledge_silo: boolean;
  }[];
  total: number;
}

/**
 * Files flagged as knowledge silos (bus factor of one).
 */
export interface Silo {
  silos: {
    file_id: string;
    file_path: string;
    primary_owner: string;
    contributors: {
      name: string;
      email: string;
      percentage: number;
      last_commit: string;
    }[];
    bus_factor: number;
    is_knowledge_silo: boolean;
  }[];
  total: number;
}
