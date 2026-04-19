export default interface ChatMessage {
  answer: string;
  sources: {
    source_type: string;
    chunk_text: string;
    file_path: string;
    symbol_name: string;
    start_line: number;
    end_line: number;
    commit_hash: string;
    author_name: string;
    pr_number: number;
    pr_title: string;
  }[];
}
