import { useState } from "react";
import { api, ApiError, describeError } from "../api";
import { MATTER_TYPES } from "../format";
import type { MatterDetail } from "../types";
import { Modal } from "./common";

interface P { name: string; role: string }

export function NewMatter({ onClose, onCreated }: { onClose: () => void; onCreated: (m: MatterDetail) => void }) {
  const [number, setNumber] = useState("");
  const [title, setTitle] = useState("");
  const [type, setType] = useState("PAYMENT_RECOVERY");
  const [forum, setForum] = useState("");
  const [parties, setParties] = useState<P[]>([{ name: "", role: "PLAINTIFF" }, { name: "", role: "DEFENDANT" }]);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null); setFieldErrors({});
    try {
      const m = await api.createMatter({ matter_number: number.trim(), title: title.trim(), matter_type: type, forum: forum.trim() || undefined, parties: parties.filter((p) => p.name.trim()).map((p) => ({ name: p.name.trim(), role: p.role })) });
      onCreated(m);
    } catch (err) {
      if (err instanceof ApiError && err.fields.length) setFieldErrors(Object.fromEntries(err.fields.map((f) => [f.field, f.message])));
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="New matter" onClose={onClose}>
      <form onSubmit={submit}>
        {error && <div role="alert" className="alert bad">{error}</div>}
        <div className="field"><label htmlFor="mn">Case number</label><input id="mn" className="input" value={number} onChange={(e) => setNumber(e.target.value)} placeholder="CS(COMM) 123/2025" required />{fieldErrors.matter_number && <span className="err">{fieldErrors.matter_number}</span>}</div>
        <div className="field"><label htmlFor="mt">Title</label><input id="mt" className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Claimant v Respondent" required /></div>
        <div className="row">
          <div className="field grow"><label htmlFor="ty">Matter type</label><select id="ty" className="select" value={type} onChange={(e) => setType(e.target.value)}>{Object.entries(MATTER_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
          <div className="field grow"><label htmlFor="fo">Forum (optional)</label><input id="fo" className="input" value={forum} onChange={(e) => setForum(e.target.value)} placeholder="High Court of Delhi" /></div>
        </div>
        <div className="field"><label>Parties (optional: they are also discovered from the documents)</label>
          {parties.map((p, i) => (
            <div className="row" key={i} style={{ marginBottom: 6 }}>
              <input className="input grow" aria-label={`Party ${i + 1} name`} value={p.name} onChange={(e) => setParties(parties.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} placeholder="Party name" />
              <select className="select" style={{ width: 140 }} aria-label={`Party ${i + 1} role`} value={p.role} onChange={(e) => setParties(parties.map((x, j) => (j === i ? { ...x, role: e.target.value } : x)))}>
                {["PLAINTIFF", "DEFENDANT", "PETITIONER", "RESPONDENT", "OTHER"].map((r) => <option key={r}>{r}</option>)}
              </select>
            </div>
          ))}
          <button type="button" className="btn sm" onClick={() => setParties([...parties, { name: "", role: "OTHER" }])}>+ Add party</button>
        </div>
        <div className="row end"><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={busy || !number.trim() || !title.trim()}>{busy ? "Creating…" : "Create matter"}</button></div>
      </form>
    </Modal>
  );
}
