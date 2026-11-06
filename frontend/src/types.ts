export type Field = { name: string; selector: string; attribute: string };
export type Config = {
  url: string;
  row_selector: string;
  fields: Field[];
  next_selector: string;
  max_pages: number;
  delay: number;
  timeout: number;
  render_js: boolean;
  deduplicate: boolean;
};
export type Result = {
  records: Record<string, string>[];
  issues: { page: string; message: string; level: string }[];
  pages: number;
  attempted: number;
  duplicates: number;
  missing: number;
  status: string;
  current_url: string | null;
  stop_reason: string;
  fields?: string[];
};
