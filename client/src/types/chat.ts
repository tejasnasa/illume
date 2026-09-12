/**
 * Chat response shapes for repository Q&A.
 * @module ChatTypes
 */
export interface ChatSource {
  source_type: string;
  chunk_text: string;
  file_path: string | null;
  symbol_name: string | null;
  start_line: number | null;
  end_line: number | null;
  commit_hash: string | null;
  author_name: string | null;
  pr_number: number | null;
  pr_title: string | null;
}

/**
 * Answer to a repository question with its RAG source citations.
 */
export default interface ChatMessage {
  answer: string;
  sources: ChatSource[];
}
