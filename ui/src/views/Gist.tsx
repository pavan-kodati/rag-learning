import { api } from "../api";
import { Empty, ErrorBox, Notes, Skeleton } from "../components/common";
import { SentenceList } from "../components/Sentences";
import { useAsync } from "../hooks";
import type { Sentence } from "../types";
import type { ViewProps } from "./shared";

export function GistView({ matterId, asOf, latest, onOpen }: ViewProps) {
  const { data, error, loading, reload } = useAsync(() => api.view(matterId, "gist", { as_of: asOf }), [matterId, asOf], latest > 0);
  if (latest === 0) return <Empty title="No documents yet">Open the “Documents” tab, upload the first batch and commit it.</Empty>;
  if (loading && !data) return <Skeleton rows={5} />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return null;
  const byId = new Map<string, Sentence>(data.sentences.map((s) => [s.id, s]));
  const meta = data.sentences.find((s) => s.kind === "meta");
  const sections: Record<string, string[]> = data.extras.sections ?? {};
  const superseded: any[] = data.extras.superseded ?? [];
  const disputed = data.sentences.filter((s) => s.state === "DISPUTED");
  return (
    <div>
      {meta && <div className="card"><b>{meta.text}</b></div>}
      <Notes notes={data.notes} />
      {disputed.length > 0 && <div className="alert warn"><b>{disputed.length} point(s) are disputed.</b> Both versions are shown, each with its source. They are not resolved by recency (the later pleading is not automatically right).</div>}
      {asOf < latest && <div className="alert info">Showing what the system understood after batch {asOf}. Facts learned later are not included.</div>}
      {Object.entries(sections).map(([label, ids]) => (
        <section key={label}>
          <div className="group-title">{label}</div>
          <SentenceList items={ids.map((i) => byId.get(i)).filter(Boolean) as Sentence[]} onOpen={onOpen} />
        </section>
      ))}
      {superseded.length > 0 && (
        <details style={{ marginTop: 22 }}>
          <summary><b>No longer valid ({superseded.length})</b> <span className="muted">earlier understanding, replaced by later documents</span></summary>
          <ul className="sentences" style={{ marginTop: 8 }}>
            {superseded.map((s) => (
              <li className="sentence SUPERSEDED" key={s.id}><span className="stext">{s.text}</span><div className="smeta">replaced by <b>{s.superseded_by_doc}</b>{s.superseded_by ? `: ${s.superseded_by}` : ""}</div></li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
