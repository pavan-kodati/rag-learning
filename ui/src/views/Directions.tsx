import { useState } from "react";
import { api } from "../api";
import { Empty, ErrorBox, Notes, Skeleton } from "../components/common";
import { CitationChip } from "../components/Sentences";
import { fmtDate, titleCase } from "../format";
import { useAsync } from "../hooks";
import type { ViewProps } from "./shared";

const FILTERS = ["ALL", "OVERDUE", "PENDING", "COMPLIED", "NO_DATE"] as const;

export function DirectionsView({ matterId, asOf, latest, today, onOpen }: ViewProps) {
  const { data, error, loading, reload } = useAsync(() => api.view(matterId, "directions", { as_of: asOf, today: today || undefined }), [matterId, asOf, today], latest > 0);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("ALL");
  if (latest === 0) return <Empty title="No directions yet">Court directions and deadlines appear once an order has been committed.</Empty>;
  if (loading && !data) return <Skeleton rows={3} />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return null;
  const rows = data.sentences.filter((s) => filter === "ALL" || s.meta?.status === filter);
  return (
    <div>
      <p className="muted">Due dates are computed by code from the order date and the period written in the order. Today is {fmtDate(data.today)}.</p>
      <div className="row" style={{ marginBottom: 12 }} role="group" aria-label="Filter by status">
        {FILTERS.map((f) => <button key={f} className={`btn sm ${filter === f ? "primary" : ""}`} aria-pressed={filter === f} onClick={() => setFilter(f)}>{titleCase(f)}</button>)}
      </div>
      <Notes notes={data.notes} />
      {rows.map((s) => (
        <div key={s.id} className="card dir">
          <div className={`due ${s.meta?.status}`}>{s.meta?.due_date ? fmtDate(s.meta.due_date) : "No date"}<small>{titleCase(String(s.meta?.status))}</small></div>
          <div>
            <div className="stext">{s.text}</div>
            <div className="smeta">{titleCase(String(s.meta?.step))} · {titleCase(String(s.meta?.kind))}{s.meta?.responsible ? ` · ${s.meta.responsible}` : ""}{s.citations.map((c, i) => <CitationChip key={i} c={c} onOpen={onOpen} />)}</div>
          </div>
        </div>
      ))}
      {!rows.length && <Empty title="Nothing matches this filter" />}
    </div>
  );
}
