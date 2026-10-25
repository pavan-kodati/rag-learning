import type { Citation, Sentence, ViewerTarget } from "../types";
import { Badge } from "./common";

export function CitationChip({ c, onOpen }: { c: Citation; onOpen: (t: ViewerTarget) => void }) {
  if (c.source_kind === "law" || !c.document_id || !c.page) {
    return <span className="cite law" title={c.quote ?? undefined}><span>{c.document_title}</span></span>;
  }
  const label = `${c.document_title}, p.${c.page}${c.structural_ref ? `, ${c.structural_ref}` : ""}`;
  return (
    <button type="button" className="cite" title={c.quote ?? "Open the source page"} aria-label={`Open source: ${label}`}
      onClick={() => onOpen({ documentId: c.document_id as string, title: c.document_title, page: c.page as number, quote: c.quote })}>
      <span>{label}</span>
    </button>
  );
}

export function StateBadge({ s }: { s: Sentence }) {
  if (s.state === "DISPUTED") return <Badge kind="disputed">Disputed</Badge>;
  if (s.state === "SUPERSEDED") return <Badge kind="gray">Superseded</Badge>;
  if (s.state === "EVIDENCE") return <Badge kind="info">{s.status === "POSSIBLE" ? "Possible evidence" : "Evidence"}</Badge>;
  return null;
}

export function SentenceItem({ s, onOpen }: { s: Sentence; onOpen: (t: ViewerTarget) => void }) {
  const unverified = s.citations.length > 0 && s.status === "UNVERIFIED";
  return (
    <li className={`sentence ${s.state} ${s.kind === "narrative" ? "narrative" : ""} ${s.status === "POSSIBLE" ? "POSSIBLE" : ""}`} data-testid="sentence">
      <span className="stext">{s.text}</span>
      <StateBadge s={s} />
      {s.kind === "narrative" && <Badge kind="warn">Summary</Badge>}
      {s.meta?.needs_review && <Badge kind="warn">Needs review</Badge>}
      {s.meta?.derived && <Badge kind="info">Computed</Badge>}
      {s.meta?.verification_status === "UNVERIFIED" && <Badge kind="warn">Unverified text</Badge>}
      {unverified && <Badge kind="bad">Unverified</Badge>}
      <div className="smeta">
        {s.citations.slice(0, 4).map((c, i) => <CitationChip key={`${c.document_id}-${c.page}-${i}`} c={c} onOpen={onOpen} />)}
        {s.superseded_by && <span>replaced by <b>{s.superseded_by}</b></span>}
        {s.meta?.source_url && <a href={s.meta.source_url} target="_blank" rel="noreferrer">source</a>}
        {s.meta?.treatment_note && <span title={s.meta.treatment_note}>treatment note</span>}
      </div>
    </li>
  );
}

export function SentenceList({ items, onOpen }: { items: Sentence[]; onOpen: (t: ViewerTarget) => void }) {
  if (!items.length) return null;
  return <ul className="sentences">{items.map((s) => <SentenceItem key={s.id} s={s} onOpen={onOpen} />)}</ul>;
}
