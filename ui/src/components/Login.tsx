import { useState } from "react";
import { api, describeError, setSession } from "../api";
import type { Session } from "../types";

export function Login({ onDone }: { onDone: (s: Session) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const r = await api.login(username.trim(), password);
      const s: Session = { username: r.username, role: r.role, token: r.access_token };
      setSession(s);
      onDone(s);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <form className="card" onSubmit={submit} aria-label="Sign in">
        <div className="brand" style={{ padding: 0, marginBottom: 14 }}><div className="brand-mark">LW</div><div><b>Legal Workspace</b><span>Sign in to continue</span></div></div>
        {error && <div role="alert" className="alert bad">{error}</div>}
        <div className="field"><label htmlFor="u">Username</label><input id="u" className="input" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus /></div>
        <div className="field"><label htmlFor="p">Password</label><input id="p" className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></div>
        <button className="btn primary block" disabled={busy || !username || !password}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </div>
  );
}
