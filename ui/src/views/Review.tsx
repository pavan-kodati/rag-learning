import { useState } from "react";
import { api, describeError } from "../api";
import { Badge, Empty, ErrorBox, Modal, Skeleton } from "../components/common";
import { CitationChip } from "../components/Sentences";
import { useAsync } from "../hooks";
import type { ReviewItem } from "../types";
import { canWrite, type ViewProps } from "./shared";

const ACTIONS: [string, string][] = [
  ["CONFIRM", "Confirm as is"], ["SUPERSEDE_OTHERS", "This is correct; end the others"], ["DISPUTE", "Keep as disputed"],
  ["EVIDENCE_ONLY", "Treat as evidence only"], ["CORRECT_VALUE", "Correct the value"], ["WITHDRAW", "Withdraw this fact"],
];

function ResolveDialog({ item, onClose, onDone }: { item: ReviewItem; onClose: () => void; onDone: () => void }) {
  const [action, setAction] = useState("CONFIRM");
  const [reason, setReason] = useState("");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function go(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try { await api.reviewFact(item.id, { action, reason: reason.trim(), value: action === "CORRECT_VALUE" ? value : undefined }); onDone(); } catch (err) { setError(describeError(err)); } finally { setBusy(false); }
  }
  return (
    <Modal title="Resolve review item" onClose={onClose}>
      <form onSubmit={go}>
        <p><b>{item.title}</b></p>
        <p className="muted">{item.reason}</p>
        {error && <div role="alert" className="alert bad">{error}</div>}
        <div className="field"><label htmlFor="ra">Decision</label><select id="ra" className="select" value={action} onChange={(e) => setAction(e.target.value)}>{ACTIONS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
        {action === "CORRECT_VALUE" && <div className="field"><label htmlFor="rv">Corrected value</label><input id="rv" className="input" value={value} onChange={(e) => setValue(e.target.value)} placeholder="e.g. Rs. 12,40,000 or 31 July 2024" /></div>}
        <div className="field"><label htmlFor="rr">Reason (recorded in the ledger with your name)</label><textarea id="rr" className="textarea" value={reason} onChange={(e) => setReason(e.target.value)} required /></div>
        <div className="row end"><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={busy || !reason.trim() || (action === "CORRECT_VALUE" && !value.trim())}>Save decision</button></div>
      </form>
    </Modal>
  );
}

export function ReviewView({ matterId, session, onOpen, onChanged }: ViewProps) {
  const { data, error, loading, reload } = useAsync(() => api.reviewQueue(matterId), [matterId]);
  const [active, setActive] = useState<ReviewItem | null>(null);
  if (loading && !data) return <Skeleton rows={3} />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return null;
  if (!data.items.length) return <Empty title="Nothing needs review">Disputed or uncertain items, unreadable documents and low-confidence scans will be listed here.</Empty>;
  return (
    <div>
      <p className="muted">These items need a person. Unresolved items stay visible as “disputed, needs review”; nothing is hidden.</p>
      {data.items.map((it) => (
        <div className="card" key={`${it.kind}-${it.id}`}>
          <div className="row"><Badge kind={it.kind === "FAILED_DOCUMENT" ? "bad" : "warn"}>{it.kind.replace(/_/g, " ").toLowerCase()}</Badge><b className="grow">{it.title}</b>
            {it.kind === "FACT" && canWrite(session) && <button className="btn sm primary" onClick={() => setActive(it)}>Resolve</button>}
            {it.kind === "DOCUMENT" && canWrite(session) && <button className="btn sm" onClick={async () => { await api.confirmDocument(it.id); reload(); onChanged(); }}>Confirm document</button>}
          </div>
          <div className="muted" style={{ marginTop: 4 }}>{it.reason}</div>
          {it.page && <div className="smeta"><CitationChip onOpen={onOpen} c={{ document_id: it.document_id, document_title: it.document, page: it.page, quote: it.quote, source_kind: "matter" }} /></div>}
        </div>
      ))}
      {active && <ResolveDialog item={active} onClose={() => setActive(null)} onDone={() => { setActive(null); reload(); onChanged(); }} />}
    </div>
  );
}
