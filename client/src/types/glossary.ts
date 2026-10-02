/**
 * Paginated glossary response shapes.
 * @module GlossaryTypes
 */

/**
 * Alphabetically ordered glossary page with total count for the query.
 *
 * The three location fields mirror the server's nullable columns: an entry
 * whose defining symbol could not be resolved carries no attribution.
 */
export default interface Glossary {
  entries: {
    id: string;
    name: string;
    definition: string;
    file_path: string | null;
    line_number: number | null;
    symbol_id: string | null;
  }[];
  total: number;
  page: number;
  page_size: number;
}
