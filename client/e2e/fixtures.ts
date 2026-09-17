import { readFileSync } from "node:fs";
import path from "node:path";

/**
 * The artifact `server/scripts/seed_e2e.py` writes.
 *
 * Specs read the repository identifiers from this rather than hardcoding them, because
 * `repo_number` is assigned by the factory's counter and would otherwise have to be kept
 * in sync by hand in two languages.
 */
export interface SeededRepo {
  name: string;
  repo_id: string;
  repo_num: number;
  file_count: number;
  github_url: string;
}

export interface Seed {
  base_url: string;
  email: string;
  password: string;
  repos: SeededRepo[];
}

/** Where the seed writes, and where `auth.setup.ts` writes the cookie state. */
export const ARTIFACT_DIR = path.join(__dirname, ".auth");
export const SEED_FILE = path.join(ARTIFACT_DIR, "seed.json");
export const STORAGE_STATE = path.join(ARTIFACT_DIR, "user.json");

/** The repository every browsing spec reads. Nothing may mutate it. */
export const PRIMARY_REPO_NAME = "seed-repo";

/** The repository the re-ingest spec is allowed to destroy. */
export const REINGEST_REPO_NAME = "reingest-me";

/** Reads the seed artifact, failing with the command to run if it is missing. */
export function readSeed(): Seed {
  try {
    return JSON.parse(readFileSync(SEED_FILE, "utf-8")) as Seed;
  } catch {
    throw new Error(
      `no seed artifact at ${SEED_FILE}. The "seed" project writes it; run ` +
        "`npx playwright test --project=seed` first, or just run the whole suite.",
    );
  }
}

/** The seeded repository with the given name, or a clear failure. */
export function repoNamed(seed: Seed, name: string): SeededRepo {
  const found = seed.repos.find((repo) => repo.name === name);
  if (!found) {
    throw new Error(
      `the seed did not create a repository named ${name}; it created ` +
        seed.repos.map((repo) => repo.name).join(", "),
    );
  }
  return found;
}
