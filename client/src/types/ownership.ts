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
