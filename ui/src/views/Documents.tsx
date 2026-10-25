import { useRef, useState } from "react";
import { api, describeError } from "../api";
import { Badge, Empty, ErrorBox, Skeleton, Spinner } from "../components/common";
import { fmtDate, titleCase } from "../format";
import { usePoll, useAsync } from "../hooks";
import type { BatchDetail, UploadResult } from "../types";
import { canWrite, type ViewProps } from "./shared";

const statusKind = (s: string): "ok" | "bad" | "warn" | "info" | "gray" => ({ PROCESSED: "ok", FAILED: "bad", EXTRACTED: "info", PROCESSING: "warn", PENDING: "gray" } as const)[s as "PROCESSED"] ?? "gray";

function BatchCard({ matterId, seq, session, onChanged, onOpen }: { matterId: string; seq: number; session: ViewProps["session"]; onChanged: () => void; onOpen: ViewProps["onOpen"] }) {
  const { data, error, loading, reload } = useAsync(() => api.batch(matterId, seq), [matterId, seq]);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "bad" | "warn"; text: string }[]>([]);
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const writable = canWrite(session);
  const active = data?.status === "PROCESSING";
  usePoll(async () => { const b = await api.batch(matterId, seq); reload(); if (b.status !== "PROCESSING") { onChanged(); return true; } return false; }, 1500, !!active);

  async function upload() {
    setBusy(true); setMsg([]);
    try {
      const r: UploadResult = await api.upload(matterId, seq, files);
      const out: { kind: "ok" | "bad" | "warn"; text: string }[] = [];
      if (r.accepted.length) out.push({ kind: "ok", text: `${r.accepted.length} file(s) uploaded.` });
      r.duplicates.forEach((d) => out.push({ kind: "warn", text: `${d.filename} is already in this matter and was skipped.` }));
      r.rejected.forEach((d) => out.push({ kind: "bad", text: `${d.filename}: ${d.reason}` }));
      setMsg(out); setFiles([]); reload();
    } catch (e) {
      setMsg([{ kind: "bad", text: describeError(e) }]);
    } finally { setBusy(false); }
  }
  async function commit() {
    setBusy(true); setMsg([]);
    try { await api.commit(matterId, seq); reload(); } catch (e) { setMsg([{ kind: "bad", text: describeError(e) }]); } finally { setBusy(false); }
  }
  async function retry() {
    setBusy(true);
    try { await api.retry(matterId, seq); reload(); } catch (e) { setMsg([{ kind: "bad", text: describeError(e) }]); } finally { setBusy(false); }
  }

  if (loading && !data) return <Skeleton rows={2} />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return null;
  const b: BatchDetail = data;
  const total = b.documents.length || 1;
  const done = b.documents.filter((d) => ["PROCESSED", "FAILED"].includes(d.status)).length;
  return (
    <div className="card">
      <div className="row"><h3 className="grow">Batch {b.batch_seq}{b.label ? ` · ${b.label}` : ""}</h3><Badge kind={b.status === "COMMITTED" ? "ok" : b.status === "FAILED" ? "bad" : b.status === "OPEN" ? "info" : "warn"}>{b.status.toLowerCase()}</Badge></div>
      {b.status === "PROCESSING" && <><div className="progress" role="progressbar" aria-valuenow={done} aria-valuemin={0} aria-valuemax={total}><i style={{ width: `${(done / total) * 100}%` }} /></div><div className="muted" style={{ margin: "6px 0" }}><Spinner label="Processing" /> Reading documents, extracting facts and reconciling with the existing matter… {b.reconcile ? `(reconcile: ${b.reconcile.toLowerCase()})` : ""}</div></>}
      {msg.map((m, i) => <div key={i} className={`alert ${m.kind}`} role={m.kind === "bad" ? "alert" : "status"}>{m.text}</div>)}
      {b.documents.length > 0 && (
        <table className="grid"><thead><tr><th>File</th><th>Type</th><th>Date</th><th>Status</th><th /></tr></thead><tbody>
          {b.documents.map((d) => (
            <tr key={d.document_id}>
              <td><b>{d.title || d.original_filename}</b><div className="muted">{d.original_filename}</div>{d.error_message && <div className="err" style={{ color: "var(--bad)" }}>{d.error_message}</div>}{d.needs_review && <Badge kind="warn">needs review</Badge>}</td>
              <td>{d.document_type ? titleCase(d.document_type) : "…"}{d.authority_class && <div className="muted">{titleCase(d.authority_class)}</div>}</td>
              <td>{fmtDate(d.document_date)}</td>
              <td><Badge kind={statusKind(d.status)}>{d.status.toLowerCase()}</Badge>{d.current_step && <div className="muted">{d.current_step}</div>}</td>
              <td>{d.total_pages && d.status !== "FAILED" ? <button className="btn sm" onClick={() => onOpen({ documentId: d.document_id, title: d.title, page: 1 })}>View</button> : null}</td>
            </tr>
          ))}
        </tbody></table>
      )}
      {b.duplicates.length > 0 && <div className="muted" style={{ marginTop: 8 }}>Duplicates skipped: {b.duplicates.map((d) => d.original_filename).join(", ")}</div>}
      {b.status === "OPEN" && writable && (
        <>
          <div className={`dropzone ${over ? "over" : ""}`} style={{ marginTop: 12 }} role="button" tabIndex={0} aria-label="Choose files to upload"
            onClick={() => input.current?.click()} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") input.current?.click(); }}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
            onDrop={(e) => { e.preventDefault(); setOver(false); setFiles([...files, ...Array.from(e.dataTransfer.files)]); }}>
            <b>Drop files here or click to choose</b><div className="muted">PDF, Word, text, e-mail (.eml) or scans (PNG / JPEG / TIFF)</div>
            <input ref={input} type="file" multiple hidden data-testid="file-input" accept=".pdf,.docx,.txt,.md,.eml,.png,.jpg,.jpeg,.tif,.tiff" onChange={(e) => { setFiles([...files, ...Array.from(e.target.files ?? [])]); e.target.value = ""; }} />
          </div>
          {files.length > 0 && <ul>{files.map((f, i) => <li key={`${f.name}-${i}`}>{f.name} <span className="muted">({Math.ceil(f.size / 1024)} KB)</span> <button className="btn sm" onClick={() => setFiles(files.filter((_, j) => j !== i))} aria-label={`Remove ${f.name}`}>✕</button></li>)}</ul>}
          <div className="row end" style={{ marginTop: 10 }}>
            <button className="btn" onClick={() => void upload()} disabled={busy || !files.length}>{busy ? "Uploading…" : `Upload ${files.length || ""} file(s)`}</button>
            <button className="btn primary" onClick={() => void commit()} disabled={busy || b.documents.length === 0} title="Close this batch and build the What-Changed report">Commit batch</button>
          </div>
        </>
      )}
      {b.status === "FAILED" && writable && <div className="row end" style={{ marginTop: 10 }}><button className="btn" onClick={() => void retry()} disabled={busy}>Retry failed steps</button></div>}
    </div>
  );
}

export function DocumentsView({ matterId, session, onChanged, onOpen }: ViewProps) {
  const matter = useAsync(() => api.matter(matterId), [matterId]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (matter.loading && !matter.data) return <Skeleton rows={3} />;
  if (matter.error) return <ErrorBox message={matter.error} onRetry={matter.reload} />;
  const m = matter.data;
  if (!m) return null;
  const open = m.batches.some((b) => b.status === "OPEN" || b.status === "PROCESSING");

  async function openBatch() {
    setBusy(true); setError(null);
    try { await api.openBatch(matterId, m!.batches.length ? `Batch ${m!.batches.length + 1}` : "Initial documents"); matter.reload(); } catch (e) { setError(describeError(e)); } finally { setBusy(false); }
  }
  return (
    <div>
      <div className="row" style={{ marginBottom: 14 }}>
        <p className="muted grow" style={{ margin: 0 }}>Documents arrive in <b>batches</b>. Each batch is processed and compared with what is already known, so you can see what changed.</p>
        {canWrite(session) && <button className="btn primary" onClick={() => void openBatch()} disabled={busy || open}>{m.batches.length ? "New batch" : "Start first batch"}</button>}
      </div>
      {error && <ErrorBox message={error} />}
      {m.batches.length === 0 && <Empty title="No documents yet">Start a batch, upload the case file and commit it.</Empty>}
      {[...m.batches].reverse().map((b) => <BatchCard key={b.batch_seq} matterId={matterId} seq={b.batch_seq} session={session} onChanged={() => { matter.reload(); onChanged(); }} onOpen={onOpen} />)}
    </div>
  );
}
