export default interface Glossary {
  entries: {
    id: string;
    name: string;
    definition: string;
    file_path: string;
    line_number: number;
    symbol_id: string;
  }[];
  total: number;
  page: number;
  page_size: number;
}
