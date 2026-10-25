import { useState } from "react";
import { api } from "../api";
import { Empty, ErrorBox, Skeleton } from "../components/common";
import { titleCase } from "../format";
import { useAsync } from "../hooks";
import type { ChangeItem } from "../types";
import type { ViewProps } from "./shared";

const KIND: Record<string, string> = { SUPERSEDED: "gray", NARROWED: "info", DISPUTED: "disputed", CONTRADICTED_BY_EVIDENCE: "bad", NEW: "ok", CORROBORATED: "info", COMPLIED: "ok" };

export function ChangesView({ matterId, latest, onOpen }: ViewProps) {
  const [batch, setBatch] = useState(latest);
  const seq = Math.min(batch, latest) || latest;
  const { data, error, loading, reload } = useAsync(() => api.changes(matterId, seq), [matterId, seq], latest > 0);
  if (latest === 0) return <Empty title="Nothing has changed yet">The report is built when a batch is committed.</Empty>;
  const open = (c: ChangeItem) => c.source_document_id && c.page && onOpen({ documentId: c.source_document_id, title: c.source_document_title, page: c.page, quote: c.quote });
  return (
    <div>
      <div className="row" style={{ marginBottom: 12 }}>
        <label htmlFor="cb" className="muted">Batch</label>
        <select id="cb" className="select" style={{ width: 130 }} value={seq} onChange={(e) => setBatch(Number(e.target.value))}>{Array.from({ length: latest }, (_, i) => i + 1).map((n) => <option key={n} value={n}>Batch {n}</option>)}</select>
      </div>
      {loading && !data && <Skeleton rows={4} />}
      {error && <ErrorBox message={error} onRetry={reload} />}
      {data && (
        <>
          <div className="chips">
            <span className="chip ok"><b>{data.documents_processed}</b> documents processed</span>
            {data.documents_failed.length > 0 && <span className="chip bad"><b>{data.documents_failed.length}</b> failed</span>}
            {data.duplicates_skipped.length > 0 && <span className="chip"><b>{data.duplicates_skipped.length}</b> duplicates skipped</span>}
          </div>
          {data.documents_failed.map((f) => <div key={f.title} className="alert bad"><b>{f.title}</b> could not be read: {f.error}. It was <b>not</b> added to the matter.</div>)}
          {data.duplicates_skipped.map((d) => <div key={d} className="alert info">Duplicate skipped: {d}</div>)}
          <div className="card">
            {data.changes.length === 0 && <div className="muted">This batch did not change the understanding of the matter.</div>}
            {data.changes.map((c) => (
              <div className="change" key={c.change_id}>
                <div><span className={`badge ${KIND[c.change_type] ?? "gray"}`}>{titleCase(c.change_type)}</span><div className="muted mono">{c.rule_id}</div></div>
                <div>
                  {c.before && c.after ? <><span className="before">{c.before}</span><span className="arrow">→</span><b>{c.after}</b></> : <b>{c.after ?? c.before}</b>}
                  {c.evidence_only && <span className="badge info" style={{ marginLeft: 6 }}>evidence only</span>}
                  <div className="smeta">{c.reason} {c.source_document_id && c.page && <button className="cite" onClick={() => open(c)}><span>{c.source_document_title}, p.{c.page}</span></button>}</div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
