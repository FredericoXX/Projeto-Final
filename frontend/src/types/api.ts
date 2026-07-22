// UUIDs do backend são strings simples na transmissão; nunca modelar como objetos.
export type UUID = string;

// Strings de data/data-hora ISO 8601. Permanecem strings nos DTOs e são
// formatadas apenas na camada de apresentação.
export type IsoDateTime = string;
export type IsoDate = string;

// Formato partilhado de todas as respostas paginadas do backend.
export interface PaginatedResponse<TItem> {
  items: TItem[];
  total: number;
  limit: number;
  offset: number;
}

// Uma ocorrência individual de validação 422 do FastAPI/Pydantic.
export interface ValidationIssue {
  loc: (string | number)[];
  msg: string;
  type: string;
}
