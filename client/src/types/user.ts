/**
 * Authenticated user profile shape.
 * @module UserTypes
 */

/**
 * Public user profile returned by the /me endpoint.
 *
 * The BYOK and free-tier fields are flattened onto the same envelope as
 * identity, so a single `GET /auth/me` call feeds the navbar, the settings
 * page and the chat quota display. The server never echoes the raw key --
 * `has_ai_key` is the boolean the UI renders.
 */
export default interface User {
  id: string;
  name: string;
  email: string;
  avatar_url: string | null;
  github_id: string | null;
  ai_provider: string | null;
  ai_model: string | null;
  has_ai_key: boolean;
  free_ingest_used: boolean;
  free_chat_messages_used: number;
}
