import { useState } from "react";
import { api, describeError } from "../api";
import { ErrorBox, Notes, Spinner } from "../components/common";
import { SentenceList } from "../components/Sentences";
import type { AskResponse } from "../types";
import type { ViewProps } from "./shared";

const SUGGESTIONS = ["Give me the gist of the matter", "What changed since the last batch?", "What has the court directed and by when?", "What are the claims and defences?", "Show me the chronology", "What does the law say about liquidated damages?"];

export function AskView({ matterId, asOf, latest, today, onOpen }: ViewProps) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<AskResponse | null>(null);

  async function ask(text: string) {
    const question = text.trim();
    if (!question) return;
    setQ(question); setBusy(true); setError(null);
    try { setRes(await api.ask(matterId, question, asOf, today || undefined)); } catch (e) { setError(describeError(e)); setRes(null); } finally { setBusy(false); }
  }

  return (
    <div>
      <form className="ask-box" onSubmit={(e) => { e.preventDefault(); void ask(q); }}>
        <div className="row">
          <input className="input grow" aria-label="Question" placeholder="Ask about this matter…" maxLength={2000} value={q} onChange={(e) => setQ(e.target.value)} disabled={latest === 0} />
          <button className="btn primary" disabled={busy || !q.trim() || latest === 0}>{busy ? <Spinner label="Thinking" /> : "Ask"}</button>
        </div>
        <div className="suggest">{SUGGESTIONS.map((s) => <button type="button" key={s} onClick={() => void ask(s)} disabled={busy || latest === 0}>{s}</button>)}</div>
        {latest === 0 && <div className="alert info" style={{ marginTop: 8 }}>Upload and commit a batch first.</div>}
      </form>
      {error && <ErrorBox message={error} />}
      {res && (
        <div aria-live="polite">
          <div className="chips">
            <span className="chip">plans: <b>{res.intents.join(", ")}</b> ({res.routed_by.toLowerCase()})</span>
            <span className="chip">as of batch <b>{res.as_of_batch_seq}</b></span>
            {res.mode === "extractive" && <span className="chip warn">extractive answer (no generation model)</span>}
            {res.unverified.length > 0 && <span className="chip warn"><b>{res.unverified.length}</b> unverified statement(s) removed</span>}
          </div>
          <Notes notes={res.notes} />
          {res.not_found.length > 0 && <div className="alert warn"><b>Not found.</b> {res.not_found.join(" ")}</div>}
          {res.sections.map((s) => (
            <section key={s.plan}>
              {res.sections.length > 1 && <div className="group-title">{s.title}</div>}
              <SentenceList items={s.sentences} onOpen={onOpen} />
            </section>
          ))}
          {res.superseded_notes.length > 0 && (
            <details style={{ marginTop: 14 }}><summary>Earlier understanding no longer valid ({res.superseded_notes.length})</summary>
              <ul>{res.superseded_notes.map((n, i) => <li key={i}><s>{n.fact}</s> {n.superseded_by ? <span className="muted">replaced by {n.superseded_by}</span> : null}</li>)}</ul>
            </details>
          )}
          {res.trace_id && <div className="trace" style={{ marginTop: 14 }}>trace {res.trace_id}{res.timings_ms ? ` · ${res.timings_ms.total_ms} ms` : ""}</div>}
        </div>
      )}
    </div>
  );
}
