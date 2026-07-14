// Backend UUIDs are plain strings on the wire; never model them as objects.
export type UUID = string;

// ISO 8601 date-time / date strings. Kept as strings in DTOs and formatted
// only in the presentation layer.
export type IsoDateTime = string;
export type IsoDate = string;

// Shared shape of every paginated list response from the backend.
export interface PaginatedResponse<TItem> {
  items: TItem[];
  total: number;
  limit: number;
  offset: number;
}

// A single FastAPI/Pydantic 422 validation issue.
export interface ValidationIssue {
  loc: (string | number)[];
  msg: string;
  type: string;
}
