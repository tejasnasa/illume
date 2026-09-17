import { setupServer } from "msw/node";

import { handlers } from "./handlers";

/**
 * Node-side MSW server shared by every test.
 *
 * Lifecycle is wired once in `tests/setup.ts`; tests only ever call `server.use(...)`
 * to override a handler for their own scenario.
 */
export const server = setupServer(...handlers);
