export default interface glossary {
  entries: {
    id: string;
    name: string;
    defintion: string;
    file_path: string;
    line_number: number;
    symbol_id: string;
  }[];
  total: number;
  page: number;
  page_size: number;
}
