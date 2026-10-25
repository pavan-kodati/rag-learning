import { useEffect, useState } from "react";
import { api, describeError } from "../api";
import type { HighlightResult, PageInfo, ViewerTarget } from "../types";
import { Spinner } from "./common";

/** Slide-over source viewer: the page image with the cited quote highlighted (blueprint §17, click-to-source). */
export function Viewer({ target, onClose }: { target: ViewerTarget; onClose: () => void }) {
  const [page, setPage] = useState(target.page);
  const [info, setInfo] = useState<PageInfo | null>(null);
  const [hl, setHl] = useState<HighlightResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showText, setShowText] = useState(false);

  useEffect(() => setPage(target.page), [target.documentId, target.page]);

  useEffect(() => {
    let live = true;
    setInfo(null); setHl(null); setError(null);
    api.page(target.documentId, page).then((p) => { if (live) setInfo(p); }, (e) => { if (live) setError(describeError(e)); });
    if (target.quote && page === target.page) {
      api.highlight(target.documentId, page, target.quote).then((h) => { if (live) setHl(h); }, () => { /* the page is still shown without a highlight */ });
    }
    return () => { live = false; };
  }, [target.documentId, target.quote, target.page, page]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const total = info?.total_pages ?? 1;
  return (
    <aside className="viewer" role="complementary" aria-label="Source document">
      <div className="viewer-head">
        <div className="grow"><b>{target.title}</b><div className="muted">Page {page}{info ? ` of ${total}` : ""}{info?.extraction_method === "OCR" ? ` · scanned page (OCR ${Math.round(info.ocr_confidence ?? 0)}%)` : ""}</div></div>
        <button className="btn sm" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page">‹</button>
        <button className="btn sm" disabled={page >= total} onClick={() => setPage(page + 1)} aria-label="Next page">›</button>
        <a className="btn sm" href={api.pdfUrl(target.documentId)} target="_blank" rel="noreferrer">Open PDF</a>
        <button className="btn sm" onClick={onClose} aria-label="Close source viewer">✕</button>
      </div>
      <div className="viewer-body">
        {error && <div role="alert" className="alert bad">{error}</div>}
        {!info && !error && <Spinner label="Loading page" />}
        {info && (
          <>
            <div className="page-wrap" data-testid="page-wrap">
              <img src={api.pageImageUrl(target.documentId, page)} alt={`${target.title}, page ${page}`} />
              {hl?.rects.map((r, i) => (
                <div key={i} className="hl" data-testid="highlight"
                  style={{ left: `${(r.x0 / info.width) * 100}%`, top: `${(r.y0 / info.height) * 100}%`, width: `${((r.x1 - r.x0) / info.width) * 100}%`, height: `${((r.y1 - r.y0) / info.height) * 100}%` }} />
              ))}
            </div>
            {target.quote && page === target.page && (
              <div className="quote-box">
                <b>Cited passage</b>{hl && !hl.found ? <span className="muted"> (could not be located exactly on the page image)</span> : hl?.approximate ? <span className="muted"> (highlighted at paragraph level)</span> : null}
                <div>“{target.quote}”</div>
              </div>
            )}
            {info.facts.length > 0 && (
              <details style={{ marginTop: 12 }}><summary>Facts recorded from this page ({info.facts.length})</summary>
                <ul>{info.facts.map((f) => <li key={f.assertion_id}>{f.assertion_text} <span className="muted">({f.state.toLowerCase()})</span></li>)}</ul>
              </details>
            )}
            <button className="btn sm" style={{ marginTop: 12 }} onClick={() => setShowText(!showText)}>{showText ? "Hide" : "Show"} extracted text</button>
            {showText && <pre className="mono" style={{ whiteSpace: "pre-wrap" }}>{info.text}</pre>}
          </>
        )}
      </div>
    </aside>
  );
}
