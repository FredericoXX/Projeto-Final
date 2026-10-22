import type { IsoDateTime, UUID } from './api';

// Um pedido existente no sistema académico, tal como recebido da fonte. O
// estado oficial é apresentado sem tradução nem interpretação.
export interface AcademicRequestRead {
  request_id: string;
  request_type: string;
  official_status: string;
  updated_at: IsoDateTime;
  next_step: string | null;
}

export type InstitutionalAccessResult =
  | 'success'
  | 'no_data'
  | 'access_denied'
  | 'not_configured'
  | 'unavailable';

// Proveniência institucional, distinta da proveniência documental das fontes.
// Acompanha também os resultados de erro, em `detail.provenance`.
export interface InstitutionalProvenanceRead {
  origin: 'institutional_api';
  simulated: boolean;
  institution_id: UUID;
  attempted_at: IsoDateTime;
  // Falso quando o backend recusou antes de consultar a fonte.
  source_consulted: boolean;
  queried_at: IsoDateTime | null;
  source_updated_at: IsoDateTime | null;
  access_result: InstitutionalAccessResult;
  fields_used: string[];
}

export interface AcademicRequestListResponse {
  outcome: 'success' | 'no_data';
  items: AcademicRequestRead[];
  provenance: InstitutionalProvenanceRead;
}

export interface AcademicRequestDetailResponse {
  outcome: 'success';
  item: AcademicRequestRead;
  provenance: InstitutionalProvenanceRead;
}

export interface AcademicRequestAccessRead {
  available: boolean;
  reason: 'available' | 'not_permitted' | 'not_configured' | 'not_linked';
  simulated: boolean;
}
