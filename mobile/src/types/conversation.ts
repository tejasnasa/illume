/**
 * Chat conversation shapes returned by the conversations endpoints.
 * @module ConversationTypes
 */

/** One conversation in a repository's list. */
export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}
