/**
 * Conversation, history and run endpoints for the streaming chat.
 *
 * @module ConversationsApi
 *
 * Every route is keyed by the repository UUID, as the rest of the chat
 * routes are.
 */

import {
  apiDelete,
  apiGet,
  apiPatch,
  type ApiRequestOptions,
} from "@/api/client";
import type { AgentRunSummary, Citation } from "@/lib/agent/types";
import type { ConversationSummary } from "@/types/conversation";

type TestOptions = Omit<ApiRequestOptions, "method" | "body">;

/** What the server knows about a stale answer, read from the chat history. */
export interface StaleInfo {
  /** The cited files that changed since the answer was given. */
  paths: string[];
}

/** One stored turn of a conversation. */
export interface HistoryRow {
  id: string;
  question: string;
  answer: string;
  sources: Partial<Citation>[] | null;
  stale_at?: string | null;
  stale_paths?: string[] | null;
}

/** A commit that touched a file an answer cited. */
export interface ChangedCommit {
  hash: string;
  message: string;
  author_name: string;
  authored_at: string;
  files: string[];
}

/** What changed under a stale answer. */
export interface AnswerChanges {
  stale_paths: string[];
  commits: ChangedCommit[];
  compare_url: string | null;
}

const base = (repoId: string) => `/api/v1/repository/${repoId}`;

/** List a repository's conversations, newest first. */
export function listConversations(
  repoId: string,
  options: TestOptions = {},
): Promise<ConversationSummary[]> {
  return apiGet(`${base(repoId)}/conversations`, options);
}

/** Rename a conversation. */
export function renameConversation(
  repoId: string,
  id: string,
  title: string,
  options: TestOptions = {},
): Promise<unknown> {
  return apiPatch(`${base(repoId)}/conversations/${id}`, { title }, options);
}

/** Delete a conversation and its turns. */
export function deleteConversation(
  repoId: string,
  id: string,
  options: TestOptions = {},
): Promise<unknown> {
  return apiDelete(`${base(repoId)}/conversations/${id}`, options);
}

/** Read one conversation's stored turns, oldest first. */
export function getConversationMessages(
  repoId: string,
  id: string,
  options: TestOptions = {},
): Promise<HistoryRow[]> {
  return apiGet(`${base(repoId)}/conversations/${id}/messages`, options);
}

/** Read the recent agent runs, which carry each answer's usage. */
export function listAgentRuns(
  repoId: string,
  options: TestOptions = {},
): Promise<AgentRunSummary[]> {
  return apiGet(`${base(repoId)}/agent-runs?limit=100`, options);
}

/** Delete one stored turn. */
export function deleteChatTurn(
  repoId: string,
  messageId: string,
  options: TestOptions = {},
): Promise<unknown> {
  return apiDelete(`${base(repoId)}/chat/${messageId}`, options);
}

/** Read what changed under a stale answer. */
export function getAnswerChanges(
  repoId: string,
  messageId: string,
  options: TestOptions = {},
): Promise<AnswerChanges> {
  return apiGet(`${base(repoId)}/chat/${messageId}/changes`, options);
}
