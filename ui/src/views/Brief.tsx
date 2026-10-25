import { useState } from "react";
import { api, describeError } from "../api";
import { Empty, ErrorBox, Spinner } from "../components/common";
import { SentenceList } from "../components/Sentences";
import { download } from "../format";
import type { Brief } from "../types";
import type { ViewProps } from "./shared";

export function BriefView({ matterId, asOf, latest, today, onOpen }: ViewProps) {
  const [brief, setBrief] = useState<Brief | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (latest === 0) return <Empty title="No brief yet">Commit at least one batch to prepare a hearing brief.</Empty>;

  async function generate() {
    setBusy(true); setError(null);
    try { setBrief(await api.brief(matterId, asOf, today || undefined)); } catch (e) { setError(describeError(e)); } finally { setBusy(false); }
  }
  return (
    <div className="brief">
      <div className="row no-print" style={{ marginBottom: 12 }}>
        <button className="btn primary" onClick={() => void generate()} disabled={busy}>{busy ? <><Spinner label="Preparing" /> Preparing…</> : brief ? "Regenerate brief" : "Prepare hearing brief"}</button>
        {brief && <><button className="btn" onClick={() => download(`hearing-brief-${brief.matter.number.replace(/\W+/g, "-")}.md`, brief.markdown)}>Download Markdown</button><button className="btn" onClick={() => window.print()}>Print / save as PDF</button></>}
        <span className="muted">Built from the position after batch {asOf}. Every line is cited to a document page.</span>
      </div>
      {error && <ErrorBox message={error} />}
      {!brief && !busy && !error && <Empty title="Ready when you are">The brief follows a fixed eight-section template: snapshot, position, issues, evidence, directions, changes, authorities and open risks.</Empty>}
      {brief && (
        <>
          <div className="card"><h2>Hearing brief: {brief.matter.title}</h2><div className="muted">{brief.matter.number} · {brief.matter.forum} · position as of batch {brief.as_of_batch_seq} · prepared {brief.generated_on}</div></div>
          {brief.sections.map((sec) => (
            <section key={sec.n} aria-label={sec.title}>
              <h2>{sec.n}. {sec.title}</h2>
              {sec.narrative.length > 0 && <SentenceList items={sec.narrative} onOpen={onOpen} />}
              <SentenceList items={sec.sentences} onOpen={onOpen} />
              {sec.notes.map((n) => <div key={n} className="muted">{n}</div>)}
            </section>
          ))}
          {brief.unverified.length > 0 && <div className="alert warn">{brief.unverified.length} statement(s) were left out because their citations could not be verified.</div>}
        </>
      )}
    </div>
  );
}
