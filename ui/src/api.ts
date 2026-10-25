import type {
  AskResponse, BatchDetail, Brief, ChangeReport, Health, HighlightResult, MatterDetail, MatterSummary, Overview, PageInfo, Party, ProblemDetails,
  ReviewItem, Session, UploadResult, ViewResponse,
} from "./types";

export class ApiError extends Error {
  status: number;
  code: string;
  requestId?: string;
  fields: { field: string; message: string }[];
  constructor(status: number, p: Partial<ProblemDetails> & { detail?: string }) {
    super(p.detail || p.title || `Request failed (${status})`);
    this.status = status;
    this.code = p.code || "error";
    this.requestId = p.request_id;
    this.fields = p.errors || [];
  }
}

const SESSION_KEY = "lw.session";
let session: Session | null = null;
let onUnauthorized: (() => void) | null = null;

export function loadSession(): Session | null {
  try {
    const raw = window.localStorage.getItem(SESSION_KEY);
    session = raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    session = null;
  }
  return session;
}
export function setSession(s: Session | null): void {
  session = s;
  try {
    if (s) window.localStorage.setItem(SESSION_KEY, JSON.stringify(s));
    else window.localStorage.removeItem(SESSION_KEY);
  } catch { /* private mode: keep the session in memory only */ }
}
export function setUnauthorizedHandler(fn: (() => void) | null): void { onUnauthorized = fn; }
export function authQuery(): string { return session?.token ? `access_token=${encodeURIComponent(session.token)}` : ""; }

async function parseProblem(r: Response): Promise<ApiError> {
  let body: any = {};
  try { body = await r.json(); } catch { /* not JSON */ }
  if (r.status === 429 && !body.detail) body.detail = "Too many requests. Wait a moment and try again.";
  if (r.status >= 500 && !body.detail) body.detail = "The server had a problem. Try again, and quote the request id if it persists.";
  if (!r.headers.get("x-request-id")) return new ApiError(r.status, body);
  return new ApiError(r.status, { ...body, request_id: body.request_id || r.headers.get("x-request-id") || undefined });
}

export async function request<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (session?.token) headers.set("Authorization", `Bearer ${session.token}`);
  let body = init.body;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }
  let r: Response;
  try {
    r = await fetch(`/api/v1${path}`, { ...init, headers, body });
  } catch {
    throw new ApiError(0, { code: "network", detail: "Cannot reach the server. Check that the API is running." });
  }
  if (!r.ok) {
    const err = await parseProblem(r);
    if (r.status === 401 && onUnauthorized) onUnauthorized();
    throw err;
  }
  if (r.status === 204) return undefined as T;
  const ct = r.headers.get("content-type") || "";
  return (ct.includes("json") ? r.json() : r.text()) as Promise<T>;
}

const q = (params: Record<string, string | number | undefined | null>): string => {
  const s = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join("&");
  return s ? `?${s}` : "";
};

export const api = {
  authConfig: () => request<{ enabled: boolean }>("/auth/config"),
  login: (username: string, password: string) => request<{ access_token: string; username: string; role: Session["role"] }>("/auth/login", { method: "POST", json: { username, password } }),
  health: () => request<Health>("/healthz"),
  matters: () => request<MatterSummary[]>("/matters"),
  matter: (id: string) => request<MatterDetail>(`/matters/${id}`),
  createMatter: (body: { matter_number: string; title: string; matter_type: string; forum?: string; parties: { name: string; role: string }[] }) => request<MatterDetail>("/matters", { method: "POST", json: body }),
  deleteMatter: (id: string) => request<void>(`/matters/${id}`, { method: "DELETE" }),
  overview: (id: string, today?: string) => request<Overview>(`/matters/${id}/overview${q({ today })}`),
  parties: (id: string) => request<Party[]>(`/matters/${id}/parties`),
  openBatch: (id: string, label?: string) => request<{ batch_seq: number }>(`/matters/${id}/batches`, { method: "POST", json: { label } }),
  batch: (id: string, seq: number) => request<BatchDetail>(`/matters/${id}/batches/${seq}`),
  upload: (id: string, seq: number, files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f, f.name));
    return request<UploadResult>(`/matters/${id}/batches/${seq}/documents`, { method: "POST", body: fd });
  },
  commit: (id: string, seq: number) => request<{ status: string }>(`/matters/${id}/batches/${seq}/commit`, { method: "POST" }),
  retry: (id: string, seq: number) => request<{ requeued: number }>(`/matters/${id}/batches/${seq}/retry`, { method: "POST" }),
  changes: (id: string, seq: number) => request<ChangeReport>(`/matters/${id}/batches/${seq}/changes`),
  view: (id: string, name: "gist" | "chronology" | "claims" | "directions" | "evidence", params: Record<string, string | number | undefined> = {}) => request<ViewResponse>(`/matters/${id}/${name}${q(params)}`),
  legal: (id: string, text: string, asOf?: number) => request<ViewResponse>(`/matters/${id}/legal${q({ q: text, as_of: asOf })}`),
  ask: (id: string, question: string, asOf?: number, today?: string) => request<AskResponse>(`/matters/${id}/ask`, { method: "POST", json: { question, as_of_batch_seq: asOf, today } }),
  brief: (id: string, asOf?: number, today?: string) => request<Brief>(`/matters/${id}/hearing-brief`, { method: "POST", json: { as_of_batch_seq: asOf, today } }),
  reviewQueue: (id: string) => request<{ count: number; items: ReviewItem[] }>(`/matters/${id}/review-queue`),
  reviewFact: (assertionId: string, body: { action: string; reason: string; value?: string }) => request<{ state: string }>(`/facts/${assertionId}/review`, { method: "POST", json: body }),
  confirmDocument: (docId: string) => request<void>(`/documents/${docId}/review-confirm`, { method: "POST" }),
  page: (docId: string, page: number) => request<PageInfo>(`/documents/${docId}/pages/${page}`),
  highlight: (docId: string, page: number, quote: string) => request<HighlightResult>(`/documents/${docId}/pages/${page}/highlight${q({ quote })}`),
  pageImageUrl: (docId: string, page: number, scale = 1.6) => `/api/v1/documents/${docId}/pages/${page}/image?scale=${scale}${authQuery() ? `&${authQuery()}` : ""}`,
  pdfUrl: (docId: string) => `/api/v1/documents/${docId}/pdf${authQuery() ? `?${authQuery()}` : ""}`,
};

export function describeError(e: unknown): string {
  if (e instanceof ApiError) return e.requestId && e.status >= 500 ? `${e.message} (request ${e.requestId})` : e.message;
  return e instanceof Error ? e.message : "Something went wrong";
}
