/**
 * Code ownership map and knowledge-silo response shapes.
 * @module OwnershipTypes
 */

/**
 * One contributor's share of a file's history. Every field but the name is
 * nullable on the server's response model.
 */
export interface Contributor {
  name: string;
  email: string | null;
  percentage: number | null;
  last_commit: string | null;
}

/**
 * Paginated per-file ownership entries with total count.
 */
export default interface Ownership {
  files: {
    file_id: string;
    file_path: string;
    primary_owner: string | null;
    contributors: Contributor[];
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
    primary_owner: string | null;
    contributors: Contributor[];
    bus_factor: number;
    is_knowledge_silo: boolean;
  }[];
  total: number;
}
