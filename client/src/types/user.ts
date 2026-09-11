/**
 * Authenticated user profile shape.
 * @module UserTypes
 */

/**
 * Public user profile returned by the /me endpoint.
 */
export default interface User {
  id: string;
  name: string;
  email: string;
  avatar_url: string | null;
  github_id: string | null;
}
