/* ============================================================
   DKMV — Screen E: Runs history + analytics
   ============================================================ */

function RunsHistory({ onOpenRun, viewState }) {
  const [wf, setWf] = useState("all");
  const [agent, setAgent] = useState("all");
  const [status, setStatus] = useState("all");
  const [sort, setSort] = useState({ key: "started", dir: "desc" });

  if (viewState === "empty") return <RunsEmpty />;

  const filtered = RUNS.filter(r =>
    (wf === "all" || r.wf === wf) &&
    (agent === "all" || r.agent === agent) &&
    (status === "all" || r.status === status)
  ).sort((a, b) => {
    const k = sort.key; let av = a[k], bv = b[k];
    if (av == null) av = 0; if (bv == null) bv = 0;
    const r = av < bv ? -1 : av > bv ? 1 : 0;
    return sort.dir === "asc" ? r : -r;
  });

  const totalSpend = RUNS.reduce((s, r) => s + r.cost, 0);
  const completed = RUNS.filter(r => r.status === "completed").length;
  const successRate = Math.round((completed / RUNS.filter(r => ["completed", "failed"].includes(r.status)).length) * 100);
  const totalTokens = RUNS.reduce((s, r) => s + r.tokensIn + r.tokensOut, 0);
  const totalHours = (RUNS.reduce((s, r) => s + (r.dur || 0), 0) / 3600);

  const setSortKey = (k) => setSort(s => ({ key: k, dir: s.key === k && s.dir === "desc" ? "asc" : "desc" }));

  return (
    <div style={{ overflowY: "auto", height: "100%", padding: "20px 24px 50px" }}>
      {/* aggregate cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr) 1.6fr", gap: 12, marginBottom: 14 }}>
        <StatCard icon={Icons.runs} label="Total runs" value={RUNS.length} />
        <StatCard icon={Icons.check} label="Success rate" value={`${successRate}%`} accent="var(--st-done)" sub={`${completed} completed`} />
        <StatCard icon={Icons.coin} label="Total spend" value={`$${totalSpend.toFixed(2)}`} accent="var(--accent)" />
        <StatCard icon={Icons.token} label="Tokens" value={`${(totalTokens / 1000).toFixed(0)}k`} />
        <StatCard icon={Icons.clock} label="Agent-hours" value={totalHours.toFixed(1)} />
        <SpendChart runs={RUNS} />
      </div>

      {/* health + retry */}
      <div style={{ display: "flex", gap: 12, marginBottom: 18 }}>
        <div className="card" style={{ flex: 1, padding: "12px 16px", display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ width: 9, height: 9, borderRadius: 99, background: "var(--st-done)", flex: "none" }} />
          <span style={{ fontSize: 13, fontWeight: 600 }}>Rate limits healthy</span>
          <span className="cap mono">Anthropic 38% · OpenAI 12% used this hour</span>
          <div style={{ flex: 1 }} />
          <div style={{ width: 120, height: 6, borderRadius: 99, background: "var(--surface-3)", overflow: "hidden" }}><div style={{ width: "38%", height: "100%", background: "var(--st-done)", borderRadius: 99 }} /></div>
        </div>
        <RetryQueue />
      </div>

      {/* filters */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
        <span className="cap" style={{ display: "flex", alignItems: "center", gap: 5, fontWeight: 600 }}><Icons.filter size={14} />Filter</span>
        <FilterSelect value={wf} onChange={setWf} options={[["all", "All workflows"], ...WORKFLOWS.map(w => [w.id, `${w.emoji} ${w.name}`])]} />
        <FilterSelect value={agent} onChange={setAgent} options={[["all", "All agents"], ["claude", "Claude"], ["codex", "Codex"]]} />
        <FilterSelect value={status} onChange={setStatus} options={[["all", "All statuses"], ["running", "Running"], ["paused", "Paused"], ["completed", "Completed"], ["failed", "Failed"], ["cancelled", "Cancelled"]]} />
        <span className="cap" style={{ marginLeft: "auto" }}>{filtered.length} of {RUNS.length} runs</span>
      </div>

      {/* table */}
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5, minWidth: 920 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)", background: "var(--surface-2)" }}>
                <Th onClick={() => setSortKey("id")} sort={sort} k="id" style={{ paddingLeft: 18 }}>Run</Th>
                <Th>Issue</Th>
                <Th>Workflow</Th>
                <Th>Agent</Th>
                <Th onClick={() => setSortKey("status")} sort={sort} k="status">Status</Th>
                <Th onClick={() => setSortKey("cost")} sort={sort} k="cost" align="right">Cost</Th>
                <Th onClick={() => setSortKey("turns")} sort={sort} k="turns" align="right">Turns</Th>
                <Th onClick={() => setSortKey("dur")} sort={sort} k="dur" align="right">Duration</Th>
                <Th onClick={() => setSortKey("started")} sort={sort} k="started">Started</Th>
                <Th></Th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r, i) => (
                <tr key={r.id} onClick={() => onOpenRun(r.id)} style={{ borderBottom: i < filtered.length - 1 ? "1px solid color-mix(in oklab, var(--border) 60%, transparent)" : "none", cursor: "pointer", transition: "background .1s" }}
                  onMouseEnter={e => e.currentTarget.style.background = "var(--surface-2)"} onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                  <td style={{ padding: "11px 12px 11px 18px", whiteSpace: "nowrap" }}><span className="mono" style={{ fontSize: 11, color: "var(--text-2)" }}>{r.id.length > 30 ? r.id.slice(0, 30) + "…" : r.id}</span></td>
                  <td style={{ padding: "11px 12px", maxWidth: 220 }}><div style={{ display: "flex", alignItems: "center", gap: 7 }}><span className="mono" style={{ color: "var(--text-3)", fontSize: 11 }}>#{r.issue}</span><span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.issueTitle}</span></div></td>
                  <td style={{ padding: "11px 12px" }}><WfChip id={r.wf} /></td>
                  <td style={{ padding: "11px 12px" }}><AgentChip id={r.agent} /></td>
                  <td style={{ padding: "11px 12px" }}><StateBadge status={r.status} /></td>
                  <td style={{ padding: "11px 12px", textAlign: "right" }}><span className="mono" style={{ fontWeight: 700 }}>${r.cost.toFixed(2)}</span></td>
                  <td style={{ padding: "11px 12px", textAlign: "right" }}><span className="mono" style={{ color: "var(--text-2)" }}>{r.turns}</span></td>
                  <td style={{ padding: "11px 12px", textAlign: "right" }}><span className="mono" style={{ color: "var(--text-2)" }}>{r.dur ? fmtDur(r.dur) : "—"}</span></td>
                  <td style={{ padding: "11px 12px" }}><span className="mono" style={{ color: "var(--text-3)", fontSize: 11 }}>{r.started.slice(5)}</span></td>
                  <td style={{ padding: "11px 16px 11px 12px", textAlign: "right" }}>{r.pr ? <span className="badge badge-soft" style={{ fontSize: 10, color: "var(--st-review)" }}><Icons.pr size={11} />#{r.pr}</span> : <Icons.chevR size={15} style={{ color: "var(--text-3)" }} />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function Th({ children, onClick, sort, k, align, style }) {
  const active = sort && sort.key === k;
  return (
    <th onClick={onClick} style={{ padding: "10px 12px", textAlign: align || "left", fontSize: 10.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".05em", color: active ? "var(--text)" : "var(--text-3)", cursor: onClick ? "pointer" : "default", whiteSpace: "nowrap", userSelect: "none", ...style }}>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 4, justifyContent: align === "right" ? "flex-end" : "flex-start" }}>
        {children}{active && <Icons.chevD size={12} style={{ transform: sort.dir === "asc" ? "rotate(180deg)" : "none" }} />}
      </span>
    </th>
  );
}

function StatCard({ icon, label, value, accent, sub }) {
  const I = icon;
  return (
    <div className="card" style={{ padding: "14px 16px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <span style={{ width: 28, height: 28, borderRadius: 8, display: "grid", placeItems: "center", background: `color-mix(in oklab, ${accent || "var(--text-3)"} 14%, transparent)`, color: accent || "var(--text-3)" }}><I size={15} /></span>
        <span className="cap" style={{ fontWeight: 600 }}>{label}</span>
      </div>
      <div className="mono" style={{ fontSize: 24, fontWeight: 800, letterSpacing: "-.02em", color: accent || "var(--text)" }}>{value}</div>
      {sub && <div className="cap" style={{ marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function SpendChart({ runs }) {
  // group spend by day
  const days = {};
  runs.forEach(r => { const d = r.started.slice(5, 10); days[d] = (days[d] || 0) + r.cost; });
  const entries = Object.entries(days).sort();
  const max = Math.max(...entries.map(e => e[1]));
  return (
    <div className="card" style={{ padding: "14px 18px", display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
        <span className="cap" style={{ fontWeight: 600, display: "flex", alignItems: "center", gap: 6 }}><Icons.chart size={14} />Spend over time</span>
        <span className="mono" style={{ fontSize: 12, fontWeight: 700 }}>${entries.reduce((s, e) => s + e[1], 0).toFixed(2)}</span>
      </div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 8, flex: 1, minHeight: 52, paddingTop: 6 }}>
        {entries.map(([d, v], i) => (
          <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 5 }}>
            <div title={`$${v.toFixed(2)}`} style={{ width: "100%", maxWidth: 32, height: `${(v / max) * 46 + 6}px`, borderRadius: "5px 5px 2px 2px", background: i === entries.length - 1 ? "var(--accent)" : "color-mix(in oklab, var(--accent) 45%, var(--surface-3))", transition: "height .4s var(--ease)" }} />
            <span className="mono" style={{ fontSize: 8.5, color: "var(--text-3)" }}>{d}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function RetryQueue() {
  const [open, setOpen] = useState(false);
  return (
    <div className="card" style={{ width: 320, flex: "none", padding: 0, overflow: "hidden", borderColor: "color-mix(in oklab, var(--st-paused) 30%, var(--border))" }}>
      <button onClick={() => setOpen(o => !o)} style={{ width: "100%", display: "flex", alignItems: "center", gap: 10, padding: "12px 16px", background: "transparent", border: 0, cursor: "pointer" }}>
        <Icons.retry size={15} style={{ color: "var(--st-paused)" }} />
        <span style={{ fontSize: 13, fontWeight: 700 }}>Retry queue</span>
        <span className="badge" style={{ background: "color-mix(in oklab, var(--st-paused) 14%, transparent)", color: "var(--st-paused)", fontSize: 10 }}>{RETRY_QUEUE.length}</span>
        <Icons.chevD size={15} style={{ marginLeft: "auto", color: "var(--text-3)", transform: open ? "rotate(180deg)" : "none", transition: "transform .15s" }} />
      </button>
      {open && (
        <div className="fade-in" style={{ padding: "0 14px 12px" }}>
          {RETRY_QUEUE.map(r => (
            <div key={r.id} style={{ padding: "10px 12px", background: "var(--surface-2)", borderRadius: 10 }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                <span className="mono" style={{ fontSize: 11, color: "var(--text-2)" }}>#{r.issue}</span>
                <span className="badge" style={{ background: "color-mix(in oklab, var(--st-paused) 14%, transparent)", color: "var(--st-paused)", fontSize: 9.5 }}>attempt {r.attempt}/3 · due in {r.dueIn}</span>
              </div>
              <div className="cap" style={{ lineHeight: 1.4 }}>{r.lastError}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function FilterSelect({ value, onChange, options }) {
  return (
    <select className="select" value={value} onChange={e => onChange(e.target.value)} style={{ width: "auto", padding: "7px 30px 7px 12px", height: 34, fontSize: 12.5, fontWeight: 600, cursor: "pointer", appearance: "none", backgroundImage: "url(\"data:image/svg+xml,%3Csvg width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23999' stroke-width='2.5' stroke-linecap='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")", backgroundRepeat: "no-repeat", backgroundPosition: "right 10px center" }}>
      {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  );
}

function RunsEmpty() {
  return (
    <div style={{ height: "100%", display: "grid", placeItems: "center", padding: 40 }}>
      <div style={{ textAlign: "center", maxWidth: 400 }} className="fade-in">
        <div style={{ width: 100, height: 100, margin: "0 auto 22px", borderRadius: 26, background: "var(--accent-soft)", display: "grid", placeItems: "center", color: "var(--accent)" }}><Icons.runs size={44} stroke={1.6} /></div>
        <h2 style={{ margin: "0 0 10px", fontSize: 21, fontWeight: 800 }}>No runs yet</h2>
        <p style={{ margin: "0 0 22px", color: "var(--text-2)", fontSize: 14.5, lineHeight: 1.55 }}>Once you run an issue, every run shows up here with its full cost, token, and duration history.</p>
        <button className="btn btn-primary btn-lg"><Icons.play size={16} />Run your first issue</button>
      </div>
    </div>
  );
}

function fmtDur(sec) { const m = Math.floor(sec / 60), s = sec % 60; return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m ${String(s).padStart(2, "0")}s`; }

Object.assign(window, { RunsHistory });
