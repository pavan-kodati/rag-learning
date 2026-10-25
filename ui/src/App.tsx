import { useCallback, useEffect, useMemo, useState } from "react";
import { api, describeError, loadSession, setSession, setUnauthorizedHandler } from "./api";
import { Empty, ErrorBox, Skeleton } from "./components/common";
import { Login } from "./components/Login";
import { NewMatter } from "./components/NewMatter";
import { Viewer } from "./components/Viewer";
import { MATTER_TYPES, fmtDate } from "./format";
import { useAsync } from "./hooks";
import type { Health, MatterSummary, Session, ViewerTarget } from "./types";
import { AskView } from "./views/Ask";
import { BriefView } from "./views/Brief";
import { ChangesView } from "./views/Changes";
import { ChronologyView } from "./views/Chronology";
import { ClaimsView } from "./views/Claims";
import { DirectionsView } from "./views/Directions";
import { DocumentsView } from "./views/Documents";
import { GistView } from "./views/Gist";
import { LegalView } from "./views/Legal";
import { ReviewView } from "./views/Review";
import type { ViewProps } from "./views/shared";

const TABS = [
  { id: "gist", label: "Position", view: GistView }, { id: "chrono", label: "Chronology", view: ChronologyView },
  { id: "claims", label: "Claims & evidence", view: ClaimsView }, { id: "directions", label: "Directions", view: DirectionsView },
  { id: "changes", label: "What changed", view: ChangesView }, { id: "ask", label: "Ask", view: AskView },
  { id: "legal", label: "Legal research", view: LegalView }, { id: "brief", label: "Hearing brief", view: BriefView },
  { id: "docs", label: "Documents", view: DocumentsView }, { id: "review", label: "Review", view: ReviewView },
] as const;
type TabId = (typeof TABS)[number]["id"];

function HealthBanner({ health }: { health: Health | null }) {
  if (!health) return null;
  const mode = health.mode;
  if (health.status === "down") return <div className="banner bad" role="alert">The database is not reachable. Nothing can be saved or read until it is back.</div>;
  if (!health.checks.llm?.ok && mode.llm_provider !== "fixture") return <div className="banner warn" role="status">The language model is not reachable ({health.checks.llm?.detail}). Uploads will wait and retry; questions fall back to extractive answers. Start Ollama and pull the models (see README).</div>;
  if (mode.llm_provider === "fixture") return <div className="banner info" role="status"><b>Demo mode.</b> Documents are read from recorded model output, so only the bundled synthetic matters can be ingested. Set LLM_PROVIDER=ollama to read your own documents.</div>;
  return null;
}

function Shell({ session, onLogout, authEnabled }: { session: Session; onLogout: () => void; authEnabled: boolean }) {
  const matters = useAsync(() => api.matters(), []);
  const health = useAsync(() => api.health().catch(() => null), []);
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [tab, setTab] = useState<TabId>("gist");
  const [asOf, setAsOf] = useState<number>(0);
  const [today, setToday] = useState("");
  const [viewer, setViewer] = useState<ViewerTarget | null>(null);
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => { setTick((t) => t + 1); matters.reload(); }, [matters]);

  useEffect(() => { const t = setInterval(() => health.reload(), 60000); return () => clearInterval(t); }, [health]);
  useEffect(() => { if (!selected && matters.data?.length) setSelected(matters.data[0].matter_id); }, [matters.data, selected]);

  const overview = useAsync(() => api.overview(selected as string, today || undefined), [selected, today, tick], !!selected);
  const latest = overview.data?.latest_batch ?? 0;
  useEffect(() => { setAsOf(latest); }, [latest, selected]);

  const current: MatterSummary | undefined = useMemo(() => matters.data?.find((m) => m.matter_id === selected), [matters.data, selected]);
  const ov = overview.data;
  const props: ViewProps | null = selected ? { matterId: selected, asOf, latest, today, session, onOpen: setViewer, onChanged: refresh } : null;
  const View = TABS.find((t) => t.id === tab)!.view;

  return (
    <div className="app">
      <aside className="sidebar" aria-label="Matters">
        <div className="brand"><div className="brand-mark">LW</div><div><b>Legal Workspace</b><span>Matter memory with sources</span></div></div>
        <div className="actions">{session.role !== "viewer" && <button className="btn primary block" onClick={() => setCreating(true)}>+ New matter</button>}</div>
        <div className="matter-list">
          {matters.loading && !matters.data && <Skeleton rows={3} />}
          {matters.error && <ErrorBox message={matters.error} onRetry={matters.reload} />}
          {matters.data?.map((m) => (
            <button key={m.matter_id} className="matter-item" aria-current={m.matter_id === selected} onClick={() => { setSelected(m.matter_id); setTab("gist"); setViewer(null); }}>
              <div className="t">{m.title}</div><div className="s">{m.matter_number} · {MATTER_TYPES[m.matter_type] ?? m.matter_type}</div><div className="s">{m.document_count} document(s) · batch {m.latest_batch}</div>
            </button>
          ))}
          {matters.data?.length === 0 && <Empty title="No matters yet">Create your first matter to begin.</Empty>}
        </div>
        <div className="sidebar-foot">
          {health.data && <div className="health" title={JSON.stringify(health.data.checks)}><span className={`dot ${health.data.status === "ok" ? "" : health.data.status === "down" ? "bad" : "warn"}`} /> {health.data.status === "ok" ? "All systems ready" : health.data.status} · {health.data.mode.llm_provider}</div>}
          <div className="row"><span className="muted grow">{session.username} ({session.role})</span>{authEnabled && <button className="btn sm" onClick={onLogout}>Sign out</button>}</div>
        </div>
      </aside>

      <main className="main">
        <HealthBanner health={health.data} />
        {!selected || !props ? (
          <div className="content"><div className="content-inner">{matters.loading ? <Skeleton rows={3} /> : <Empty title="Select or create a matter">Matters keep a persistent, source-linked understanding of a case as documents arrive.</Empty>}</div></div>
        ) : (
          <>
            <div className="topbar">
              <div className="title-row">
                <div><h1>{current?.title ?? ov?.title}</h1><div className="muted">{current?.matter_number} · {current?.current_forum ?? "forum not set"}</div></div>
                <div className="row no-print">
                  {latest > 0 && <><label className="muted" htmlFor="asof">View as of</label>
                    <select id="asof" className="select" style={{ width: 160 }} value={asOf} onChange={(e) => setAsOf(Number(e.target.value))}>{Array.from({ length: latest }, (_, i) => i + 1).map((n) => <option key={n} value={n}>Batch {n}{n === latest ? " (latest)" : ""}</option>)}</select></>}
                  <label className="muted" htmlFor="today" title="Deadlines are measured against this date. Leave blank for today.">Today</label>
                  <input id="today" type="date" className="input" style={{ width: 150 }} value={today} onChange={(e) => setToday(e.target.value)} />
                </div>
              </div>
              {ov && (
                <div className="chips" aria-label="Matter summary">
                  <span className="chip"><b>{ov.documents}</b> documents</span><span className="chip"><b>{ov.facts}</b> current facts</span>
                  {ov.disputed > 0 && <span className="chip warn"><b>{ov.disputed}</b> disputed</span>}
                  {ov.overdue > 0 && <span className="chip bad"><b>{ov.overdue}</b> overdue</span>}
                  {ov.next_hearing && <span className="chip ok">next hearing <b>{fmtDate(ov.next_hearing.date)}</b></span>}
                </div>
              )}
              <div className="tabs" role="tablist">
                {TABS.map((t) => (
                  <button key={t.id} role="tab" aria-selected={tab === t.id} className="tab" onClick={() => setTab(t.id)}>
                    {t.label}{t.id === "review" && ov && ov.review_items > 0 ? <span className="count">{ov.review_items}</span> : null}
                  </button>
                ))}
              </div>
            </div>
            <div className="content" role="tabpanel"><div className="content-inner"><View key={`${selected}-${tab}-${tick}`} {...props} /></div></div>
          </>
        )}
      </main>

      {viewer && <Viewer target={viewer} onClose={() => setViewer(null)} />}
      {creating && <NewMatter onClose={() => setCreating(false)} onCreated={(m) => { setCreating(false); setSelected(m.matter_id); setTab("docs"); refresh(); }} />}
    </div>
  );
}

export default function App() {
  const [session, setSess] = useState<Session | null>(() => loadSession());
  const [authEnabled, setAuthEnabled] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.authConfig().then((c) => setAuthEnabled(c.enabled), (e) => { setError(describeError(e)); setAuthEnabled(false); });
  }, []);
  useEffect(() => {
    setUnauthorizedHandler(() => { setSession(null); setSess(null); });
    return () => setUnauthorizedHandler(null);
  }, []);

  if (authEnabled === null) return <div className="login"><Skeleton rows={1} /></div>;
  if (authEnabled && !session) return <Login onDone={setSess} />;
  const effective: Session = session ?? { username: "local", role: "admin", token: null };
  return (
    <>
      {error && <div className="banner bad" role="alert">{error}</div>}
      <Shell session={effective} authEnabled={authEnabled} onLogout={() => { setSession(null); setSess(null); }} />
    </>
  );
}
