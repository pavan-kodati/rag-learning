import type { ReactNode } from "react";

export function Spinner({ label = "Loading" }: { label?: string }) {
  return <span role="status" aria-label={label} className="spinner" />;
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return <div aria-busy="true" aria-label="Loading">{Array.from({ length: rows }, (_, i) => <div key={i} className="skeleton" />)}</div>;
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="alert bad">
      <b>Something went wrong.</b> {message}
      {onRetry && <> <button className="btn sm" onClick={onRetry}>Try again</button></>}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty"><b>{title}</b>{children}</div>;
}

export function Notes({ notes }: { notes?: string[] }) {
  if (!notes?.length) return null;
  return <>{[...new Set(notes)].map((n) => <div key={n} className="alert info">{n}</div>)}</>;
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="modal-back" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}

export function Badge({ kind, children }: { kind: "ok" | "bad" | "warn" | "disputed" | "info" | "gray"; children: ReactNode }) {
  return <span className={`badge ${kind}`}>{children}</span>;
}
