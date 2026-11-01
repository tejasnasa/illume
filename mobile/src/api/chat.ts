/**
 * Repository chat endpoints.
 *
 * @module ChatApi
 *
 * Port of the web client's ``client/src/api/chat.ts`` plus the four routes
 * the web hook drives directly (``server/app/api/v1/chat.py``).
 *
 * The chat routes are keyed by the repository's **UUID**, not by the
 * user-scoped ``repo_number`` the dashboard links on. Mixing the two up
 * returns a 404 that reads like "no chat yet" rather than "wrong id", so
 * every function here takes the UUID and the caller has to resolve it
 * first.
 *
 * The four calls are:
 *
 * - ``POST   /api/v1/repository/{id}/chat``            ask a question
 * - ``GET    /api/v1/repository/{id}/chat/history``    read the history
 * - ``DELETE /api/v1/repository/{id}/chat/{message}`` drop one turn
 * - ``DELETE /api/v1/repository/{id}/chat``            drop every turn
 */

import {
  apiDelete,
  apiGet,
  apiPost,
  type ApiRequestOptions,
} from "@/api/client";
import type { default as ChatMessage, ChatSource } from "@/types/chat";

/**
 * Transport overrides a caller may inject. Production callers leave the bag
 * empty; tests supply a ``backendUrl`` and a ``fetchImpl``.
 */
type TestOptions = Omit<ApiRequestOptions, "method" | "body">;

/**
 * One prior conversation turn sent along with a question.
 *
 * The server keeps only the last five of these, and truncates on its own
 * side -- the client sends everything it has and lets the server decide.
 */
export interface ChatHistoryEntry {
  /** Who produced the turn: the reader or the assistant. */
  role: "user" | "assistant";
  /** The turn's text. An assistant turn is a markdown answer. */
  content: string;
}

/**
 * Body accepted by the chat endpoint.
 */
export interface ChatRequest {
  /** The question being asked. */
  question: string;
  /** Prior turns, oldest first. */
  history: ChatHistoryEntry[];
}

/**
 * A newly created turn: the answer and the sources that back it.
 */
export interface ChatResponse {
  /** The persisted turn's id. */
  id: string;
  /** The generated answer, as markdown. */
  answer: string;
  /** The sources cited by the answer. */
  sources: ChatSource[];
}

/**
 * A persisted turn as the history endpoint returns it.
 *
 * The history rows carry the fields the chat table stores; only the
 * question, the answer and the sources are of interest to the reader, but
 * the whole record is typed so a caller can reach the rest.
 */
export interface ChatHistoryTurn {
  /** The turn's id. */
  id: string;
  /** The repository the turn belongs to. */
  repository_id: string;
  /** The reader the turn belongs to. */
  user_id: string;
  /** The question that was asked. */
  question: string;
  /** The answer that came back, as markdown. */
  answer: string;
  /** The sources cited by the answer, or ``null`` when the row has none. */
  sources: ChatSource[] | null;
  /** When the turn was recorded. */
  created_at: string;
}

/**
 * Build the path of a repository's chat collection.
 *
 * @param repoId - The repository's UUID.
 * @returns The absolute API path.
 */
function chatPath(repoId: string): string {
  return `/api/v1/repository/${repoId}/chat`;
}

/**
 * Ask a question about a repository.
 *
 * The response is 402 when the free-tier allowance is spent; the error
 * carries the server's own wording, which the caller shows to the reader.
 *
 * @param repoId - The repository's UUID.
 * @param payload - The question and the prior turns.
 * @param options - Test-friendly transport overrides.
 * @returns The new turn's id, answer and sources.
 */
export function postChatQuestion(
  repoId: string,
  payload: ChatRequest,
  options: TestOptions = {},
): Promise<ChatResponse> {
  return apiPost<ChatResponse>(chatPath(repoId), payload, options);
}

/**
 * Read the persisted chat history of a repository, oldest turn first.
 *
 * @param repoId - The repository's UUID.
 * @param options - Test-friendly transport overrides.
 * @returns The stored turns.
 */
export function getChatHistory(
  repoId: string,
  options: TestOptions = {},
): Promise<ChatHistoryTurn[]> {
  return apiGet<ChatHistoryTurn[]>(`${chatPath(repoId)}/history`, options);
}

/**
 * Delete one persisted turn.
 *
 * @param repoId - The repository's UUID.
 * @param messageId - The turn's id.
 * @param options - Test-friendly transport overrides.
 * @returns Nothing; the endpoint answers 204.
 */
export function deleteChatMessage(
  repoId: string,
  messageId: string,
  options: TestOptions = {},
): Promise<void> {
  return apiDelete<void>(`${chatPath(repoId)}/${messageId}`, options);
}

/**
 * Delete every persisted turn of a repository.
 *
 * @param repoId - The repository's UUID.
 * @param options - Test-friendly transport overrides.
 * @returns Nothing; the endpoint answers 204.
 */
export function clearChatHistory(
  repoId: string,
  options: TestOptions = {},
): Promise<void> {
  return apiDelete<void>(chatPath(repoId), options);
}

/**
 * The answer payload a turn carries, with its citations.
 *
 * The chat table stores the sources as a JSON blob, so a row read back from
 * the history endpoint can carry ``null`` where a fresh answer carries a
 * list. This narrows both to the shape the UI renders.
 *
 * @param answer - The answer text.
 * @param sources - The stored sources, if any.
 * @returns The answer payload.
 */
export function toChatMessage(
  answer: string,
  sources?: ChatSource[] | null,
): ChatMessage {
  return { answer, sources: sources ?? [] };
}
