import { api } from "../api";
import { Empty, ErrorBox, Notes, Skeleton } from "../components/common";
import { StateBadge, CitationChip } from "../components/Sentences";
import { useAsync } from "../hooks";
import type { ViewProps } from "./shared";

export function ChronologyView({ matterId, asOf, latest, onOpen }: ViewProps) {
  const { data, error, loading, reload } = useAsync(() => api.view(matterId, "chronology", { as_of: asOf }), [matterId, asOf], latest > 0);
  if (latest === 0) return <Empty title="No chronology yet">Events appear once a batch has been committed.</Empty>;
  if (loading && !data) return <Skeleton rows={6} />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return null;
  if (!data.sentences.length) return <><Notes notes={data.notes} /><Empty title="No dated events found" /></>;
  return (
    <div>
      <p className="muted">Sorted by real-world date. Superseded items are struck through with the document that replaced them; disputed items are flagged.</p>
      <ol className="timeline">
        {data.sentences.map((s) => (
          <li key={s.id} className={`tl-item ${s.state}`}>
            <div className={`sentence ${s.state}`}>
              <span className="stext">{s.text}</span> <StateBadge s={s} />
              <div className="smeta">
                {s.citations.map((c, i) => <CitationChip key={i} c={c} onOpen={onOpen} />)}
                {s.superseded_by && <span>replaced by <b>{s.superseded_by}</b></span>}
                <span>learned in batch {s.meta?.learned_in_batch}</span>
              </div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
