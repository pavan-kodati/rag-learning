export interface Citation {
  document_id: string | null;
  document_title: string;
  page: number | null;
  quote: string | null;
  structural_ref?: string | null;
  source_kind: "matter" | "law";
  source_id?: string | null;
}

export interface Sentence {
  id: string;
  text: string;
  status: "VERIFIED" | "INFO" | "POSSIBLE" | "UNVERIFIED";
  state: "CURRENT" | "DISPUTED" | "SUPERSEDED" | "EVIDENCE" | "INFO";
  kind: string;
  plan?: string;
  citations: Citation[];
  superseded_by?: string | null;
  meta?: Record<string, any>;
}

export interface Rejected { id: string; text: string; reasons: string[] }

export interface ViewResponse {
  as_of_batch_seq: number;
  plan: string;
  title?: string;
  sentences: Sentence[];
  unverified?: Rejected[];
  notes: string[];
  extras: Record<string, any>;
  today?: string;
}

export interface Party { party_id: string; canonical_name: string; role: string; aliases: string[] }
export interface Batch { batch_seq: number; label: string | null; status: "OPEN" | "PROCESSING" | "COMMITTED" | "FAILED"; document_count?: number; committed_at?: string | null }

export interface MatterSummary {
  matter_id: string; matter_number: string; title: string; matter_type: string; current_forum: string | null;
  latest_batch: number; document_count: number; created_at: string;
}
export interface MatterDetail extends MatterSummary { parties: Party[]; batches: Batch[] }

export interface Overview {
  matter_id: string; title: string; latest_batch: number; documents: number; facts: number; disputed: number; overdue: number;
  review_items: number; next_hearing: { date: string; text: string } | null; documents_by_status: Record<string, number>;
}

export interface DocumentRow {
  document_id: string; original_filename: string; title: string; status: string; document_type: string | null; document_date: string | null;
  authority_class: string | null; current_step: string | null; error_message: string | null; needs_review: boolean; total_pages: number | null;
}
export interface BatchDetail extends Batch {
  documents: DocumentRow[]; duplicates: { original_filename: string }[]; progress: Record<string, number>; reconcile: string | null;
}

export interface UploadResult {
  accepted: { document_id: string; filename: string }[];
  duplicates: { filename: string; duplicate_of: string }[];
  rejected: { filename: string; code: string; reason: string }[];
}

export interface ChangeItem {
  change_id: number; change_type: string; rule_id: string; before: string | null; after: string | null; reason: string | null;
  source_document_title: string; page: number | null; evidence_only: boolean; quote: string | null; source_document_id: string | null;
}
export interface ChangeReport {
  batch_seq: number; documents_processed: number; documents_failed: { title: string; error: string }[]; duplicates_skipped: string[]; changes: ChangeItem[];
}

export interface AskResponse {
  question: string; as_of_batch_seq: number; intents: string[]; routed_by: string; answer_sentences: Sentence[];
  sections: { plan: string; title: string; sentences: Sentence[]; notes: string[]; extras: Record<string, any> }[];
  not_found: string[]; superseded_notes: { fact: string; superseded_by: string | null }[]; unverified: Rejected[]; notes: string[];
  mode: string; trace_id: string | null; timings_ms?: Record<string, number>;
}

export interface BriefSection { n: number; title: string; sentences: Sentence[]; narrative: Sentence[]; notes: string[] }
export interface Brief {
  matter: { id: string; title: string; number: string; forum: string | null }; as_of_batch_seq: number; generated_on: string;
  sections: BriefSection[]; unverified: Rejected[]; markdown: string; changes_from_batch: number;
}

export interface ReviewItem {
  kind: "FACT" | "DOCUMENT" | "FAILED_DOCUMENT" | "LOW_OCR_PAGE"; id: string; title: string; reason: string | null; state: string;
  document: string; document_id: string; page: number | null; quote: string | null; batch_seq: number; fact_key?: string;
}

export interface Health {
  status: "ok" | "degraded" | "down"; version: string; corpus_passages: number;
  checks: Record<string, { ok: boolean; detail?: string }>;
  mode: { llm_provider: string; embedder: string; reranker: string; models: Record<string, string> };
}

export interface ProblemDetails { code: string; title: string; detail: string; status: number; request_id?: string; errors?: { field: string; message: string }[] }

export interface PageInfo {
  document_id: string; title: string; page: number; total_pages: number; text: string; width: number; height: number;
  extraction_method: string; ocr_confidence: number | null; facts: { assertion_id: string; assertion_text: string; source_quote: string; state: string }[];
}
export interface HighlightResult { width: number; height: number; found: boolean; approximate?: boolean; rects: { x0: number; y0: number; x1: number; y1: number; page: number }[] }

export interface Session { username: string; role: "viewer" | "analyst" | "admin"; token: string | null }
export interface ViewerTarget { documentId: string; title: string; page: number; quote?: string | null }
