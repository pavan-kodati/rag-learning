import { useState } from "react";
import { api, describeError } from "../api";
import { Empty, ErrorBox, Notes, Skeleton } from "../components/common";
import { CitationChip, StateBadge } from "../components/Sentences";
import { useAsync } from "../hooks";
import type { Sentence } from "../types";
import type { ViewProps } from "./shared";

function Claim({ s, matterId, asOf, onOpen }: { s: Sentence } & Pick<ViewProps, "matterId" | "asOf" | "onOpen">) {
  const ev = s.meta?.evidence ?? { for: [], against: [] };
  const [more, setMore] = useState<Sentence[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function find() {
    setBusy(true); setErr(null);
    try {
      const r = await api.view(matterId, "evidence", { q: s.text, as_of: asOf });
      setMore(r.sentences.filter((x) => x.kind === "possible_evidence"));
    } catch (e) { setErr(describeError(e)); } finally { setBusy(false); }
  }
  return (
    <div className="claim">
      <span className="stext">{s.text}</span> <StateBadge s={s} />
      <div className="smeta">{s.citations.map((c, i) => <CitationChip key={i} c={c} onOpen={onOpen} />)}<span>{String(s.meta?.category ?? "").toLowerCase().replace("_", " ")}</span></div>
      {(ev.for.length > 0 || ev.against.length > 0) && (
        <ul className="ev-list">
          {ev.for.map((e: any) => <li className="for" key={`f${e.fact_id}`}><b>Supports:</b> {e.text} <button className="cite" onClick={() => onOpen({ documentId: e.document_id, title: e.document, page: e.page, quote: e.quote })}><span>{e.document}, p.{e.page}</span></button></li>)}
          {ev.against.map((e: any) => <li className="against" key={`a${e.fact_id}`}><b>Contradicts:</b> {e.text} <button className="cite" onClick={() => onOpen({ documentId: e.document_id, title: e.document, page: e.page, quote: e.quote })}><span>{e.document}, p.{e.page}</span></button></li>)}
        </ul>
      )}
      <div style={{ marginTop: 6 }}>
        <button className="btn sm" onClick={find} disabled={busy}>{busy ? "Searching…" : "Find more evidence"}</button>
        {err && <span className="err"> {err}</span>}
      </div>
      {more && (more.length ? (
        <ul className="ev-list">{more.map((m) => <li key={m.id}><span className="badge info">possible evidence</span> {m.text} {m.citations.map((c, i) => <CitationChip key={i} c={c} onOpen={onOpen} />)}</li>)}</ul>
      ) : <div className="muted" style={{ marginTop: 4 }}>No other passages found.</div>)}
    </div>
  );
}

export function ClaimsView(p: ViewProps) {
  const { data, error, loading, reload } = useAsync(() => api.view(p.matterId, "claims", { as_of: p.asOf }), [p.matterId, p.asOf], p.latest > 0);
  if (p.latest === 0) return <Empty title="No claims yet">Claims, defences and reliefs appear once documents are committed.</Empty>;
  if (loading && !data) return <Skeleton rows={4} />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return null;
  const byParty: Record<string, string[]> = data.extras.by_party ?? {};
  const byId = new Map(data.sentences.map((s) => [s.id, s]));
  if (!data.sentences.length) return <><Notes notes={data.notes} /><Empty title="No claims found" /></>;
  return (
    <div className="board">
      {Object.entries(byParty).map(([party, ids]) => (
        <div className="card" key={party}>
          <h3>{party}</h3>
          {ids.map((id) => byId.get(id)).filter(Boolean).map((s) => <Claim key={(s as Sentence).id} s={s as Sentence} matterId={p.matterId} asOf={p.asOf} onOpen={p.onOpen} />)}
        </div>
      ))}
    </div>
  );
}
