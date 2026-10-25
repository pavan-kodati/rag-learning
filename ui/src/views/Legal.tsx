import { useState } from "react";
import { api } from "../api";
import { Empty, ErrorBox, Notes, Skeleton } from "../components/common";
import { SentenceList } from "../components/Sentences";
import { useAsync } from "../hooks";
import type { ViewProps } from "./shared";

export function LegalView({ matterId, asOf, latest, onOpen }: ViewProps) {
  const [text, setText] = useState("");
  const [submitted, setSubmitted] = useState("");
  const { data, error, loading, reload } = useAsync(() => api.legal(matterId, submitted, asOf || undefined), [matterId, asOf, submitted], latest > 0);
  if (latest === 0) return <Empty title="No legal context yet">Authorities are chosen from the issues in dispute, so commit a batch first.</Empty>;
  const tags: string[] = data?.extras.issue_tags ?? [];
  return (
    <div>
      <form className="row" style={{ marginBottom: 12 }} onSubmit={(e) => { e.preventDefault(); setSubmitted(text.trim()); }}>
        <input className="input grow" aria-label="Legal question" placeholder="e.g. liquidated damages and penalty, pre-institution mediation…" value={text} onChange={(e) => setText(e.target.value)} />
        <button className="btn primary">Search authorities</button>
      </form>
      {tags.length > 0 && <div className="chips">{tags.slice(0, 10).map((t) => <span className="chip" key={t}>{t.replace(/_/g, " ")}</span>)}</div>}
      <div className="alert warn">The starter corpus holds <b>paraphrased summaries</b>, shown as “unverified text”. Check the official text on India Code or SCR before relying on any authority.</div>
      {loading && !data && <Skeleton rows={4} />}
      {error && <ErrorBox message={error} onRetry={reload} />}
      {data && <><Notes notes={data.notes} /><SentenceList items={data.sentences} onOpen={onOpen} /></>}
    </div>
  );
}
