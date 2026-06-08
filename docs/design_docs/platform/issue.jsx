/* ============================================================
   DKMV — Screen C: Issue detail + assign workflow (launch)
   ============================================================ */

// tiny markdown-ish renderer for issue bodies
function MD({ text }) {
  const blocks = text.split("\n");
  const out = [];
  let i = 0;
  while (i < blocks.length) {
    const line = blocks[i];
    if (line.startsWith("### ")) out.push(<h4 key={i} style={{ margin: "18px 0 8px", fontSize: 14, fontWeight: 800, letterSpacing: "-.01em" }}>{line.slice(4)}</h4>);
    else if (/^\d+\.\s/.test(line)) {
      const items = [];
      while (i < blocks.length && /^\d+\.\s/.test(blocks[i])) { items.push(blocks[i].replace(/^\d+\.\s/, "")); i++; }
      out.push(<ol key={i} style={{ margin: "6px 0", paddingLeft: 22, color: "var(--text-2)", fontSize: 14, lineHeight: 1.7 }}>{items.map((t, j) => <li key={j}><Inline t={t} /></li>)}</ol>);
      continue;
    }
    else if (line.startsWith("- ")) {
      const items = [];
      while (i < blocks.length && blocks[i].startsWith("- ")) { items.push(blocks[i].slice(2)); i++; }
      out.push(<ul key={i} style={{ margin: "6px 0", paddingLeft: 20, color: "var(--text-2)", fontSize: 14, lineHeight: 1.7 }}>{items.map((t, j) => <li key={j}><Inline t={t} /></li>)}</ul>);
      continue;
    }
    else if (line.trim() === "") out.push(<div key={i} style={{ height: 6 }} />);
    else out.push(<p key={i} style={{ margin: "0 0 8px", color: "var(--text-2)", fontSize: 14, lineHeight: 1.65 }}><Inline t={line} /></p>);
    i++;
  }
  return <div>{out}</div>;
}
function Inline({ t }) {
  const parts = t.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
  return parts.map((p, i) => {
    if (p.startsWith("`")) return <code key={i} className="mono" style={{ fontSize: 12.5, background: "var(--surface-2)", padding: "1px 6px", borderRadius: 5, border: "1px solid var(--border)" }}>{p.slice(1, -1)}</code>;
    if (p.startsWith("**")) return <strong key={i} style={{ color: "var(--text)", fontWeight: 700 }}>{p.slice(2, -2)}</strong>;
    return p;
  });
}

function IssueDetail({ issue, onLaunch, onBack }) {
  if (!issue) return null;
  const hasRun = !!issue.run;
  const [wf, setWf] = useState(issue.workflow || "dev");
  const [agent, setAgent] = useState(issue.agent && issue.agent !== "auto" ? issue.agent : "auto");
  const [branch, setBranch] = useState(`dkmv/issue-${issue.num}-${issue.title.toLowerCase().split(" ").slice(0, 3).join("-").replace(/[^a-z0-9-]/g, "")}`);
  const [advanced, setAdvanced] = useState(false);
  const [budget, setBudget] = useState("");
  const w = WF[wf];
  const resolvedAgent = agent === "auto" ? w.agent : agent;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 408px", gap: 0, height: "100%", minHeight: 0 }}>
      {/* LEFT — the issue */}
      <div style={{ overflowY: "auto", padding: "26px 30px 60px" }}>
        <div style={{ maxWidth: 720 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
            <span className="mono" style={{ fontSize: 14, color: "var(--text-3)", fontWeight: 600 }}>#{issue.num}</span>
            <StateBadge status={issue.state} />
            {hasRun && <span className="cap" style={{ display: "flex", alignItems: "center", gap: 5 }}><Icons.branch size={12} />on <span className="mono" style={{ fontSize: 11.5 }}>feat/codex</span></span>}
            <button className="btn btn-ghost btn-sm" style={{ marginLeft: "auto" }}><Icons.github size={14} />Open on GitHub<Icons.ext size={13} /></button>
          </div>
          <h1 style={{ margin: "0 0 14px", fontSize: 25, fontWeight: 800, letterSpacing: "-.025em", lineHeight: 1.25, textWrap: "balance" }}>{issue.title}</h1>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 18 }}>
            <Avatar initials="AS" size={26} color="var(--st-review)" />
            <span style={{ fontSize: 13.5 }}><span style={{ fontWeight: 700 }}>asaficontact</span> <span style={{ color: "var(--text-3)" }}>opened this issue</span></span>
            <div style={{ display: "flex", gap: 5, marginLeft: "auto", flexWrap: "wrap" }}>{issue.labels.map(l => <GhLabel key={l} name={l} />)}</div>
          </div>

          {hasRun && (
            <div className="card" style={{ padding: 14, marginBottom: 20, borderColor: issue.state === "needsyou" ? "color-mix(in oklab, var(--st-paused) 40%, transparent)" : "color-mix(in oklab, var(--st-running) 30%, transparent)", display: "flex", alignItems: "center", gap: 13, background: issue.state === "needsyou" ? "color-mix(in oklab, var(--st-paused) 8%, transparent)" : "color-mix(in oklab, var(--st-running) 6%, transparent)" }}>
              <span style={{ width: 38, height: 38, borderRadius: 11, display: "grid", placeItems: "center", flex: "none", background: `color-mix(in oklab, var(--st-${STATE_OF[issue.state]}) 16%, transparent)`, color: `var(--st-${STATE_OF[issue.state]})` }}>{issue.state === "needsyou" ? <Icons.pause size={18} /> : <Icons.bolt size={18} />}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13.5, fontWeight: 700 }}>{issue.state === "needsyou" ? "This run is paused and needs your decision" : "A run is in progress for this issue"}</div>
                <div className="cap mono" style={{ marginTop: 2, fontSize: 11 }}>{issue.run}</div>
              </div>
              <button className="btn btn-soft" onClick={() => onLaunch()}>{issue.state === "needsyou" ? "Review decision" : "Watch live"}<Icons.arrowR size={15} /></button>
            </div>
          )}

          <div className="card" style={{ padding: "8px 20px 18px" }}>
            <MD text={issue.body} />
          </div>

          {issue.comments && issue.comments.length > 0 && (
            <div style={{ marginTop: 22 }}>
              <div className="cap" style={{ fontWeight: 700, textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 12 }}>{issue.comments.length} comment{issue.comments.length > 1 ? "s" : ""}</div>
              {issue.comments.map((c, i) => (
                <div key={i} style={{ display: "flex", gap: 12, marginBottom: 14 }}>
                  <Avatar initials={c.avatar} size={30} color="var(--st-review)" />
                  <div className="card" style={{ flex: 1, padding: "11px 14px" }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 5 }}>
                      <span style={{ fontSize: 13, fontWeight: 700 }}>{c.author}</span>
                      <span className="cap">{c.time}</span>
                    </div>
                    <div style={{ fontSize: 13.5, color: "var(--text-2)", lineHeight: 1.55 }}>{c.body}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* RIGHT — run panel */}
      <div style={{ borderLeft: "1px solid var(--border)", background: "var(--surface)", overflowY: "auto", display: "flex", flexDirection: "column" }}>
        <div style={{ padding: "22px 22px 18px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 4 }}>
            <Icons.play size={17} style={{ color: "var(--accent)" }} />
            <h2 style={{ margin: 0, fontSize: 17, fontWeight: 800, letterSpacing: "-.02em" }}>Run this issue</h2>
          </div>
          <p style={{ margin: 0, color: "var(--text-2)", fontSize: 13 }}>Pick a workflow and let's go. You can change everything later.</p>
        </div>
        <hr className="divider" />

        <div style={{ padding: "18px 22px", display: "flex", flexDirection: "column", gap: 20, flex: 1 }}>
          {/* workflow */}
          <Field label="Workflow" hint="What pipeline should the agent run?">
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {WORKFLOWS.filter(x => ["plan", "dev", "qa", "docs"].includes(x.id)).map(x => {
                const active = wf === x.id;
                return (
                  <button key={x.id} onClick={() => setWf(x.id)}
                    style={{ textAlign: "left", padding: "11px 13px", borderRadius: 12, cursor: "pointer", transition: "all .14s",
                      border: `1px solid ${active ? "var(--accent-ring)" : "var(--border)"}`, background: active ? "var(--accent-soft)" : "var(--surface-2)" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 6 }}>
                      <span style={{ fontSize: 16 }}>{x.emoji}</span>
                      <span style={{ fontSize: 14, fontWeight: 700 }}>{x.name}</span>
                      <span className="cap" style={{ marginLeft: 2 }}>{x.purpose}</span>
                      {x.pauses && <span className="badge" style={{ marginLeft: "auto", background: "color-mix(in oklab, var(--st-paused) 13%, transparent)", color: "var(--st-paused)", fontSize: 10 }}><Icons.pause size={9} />pauses</span>}
                    </div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 5, alignItems: "center" }}>
                      {x.stages.map((s, si) => (
                        <React.Fragment key={si}>
                          {si > 0 && <Icons.chevR size={11} style={{ color: "var(--text-3)" }} />}
                          <span className="mono" style={{ fontSize: 10.5, color: active ? "var(--accent)" : "var(--text-3)", fontWeight: 600 }}>{s.replace(" ×N (for-each phase)", "")}</span>
                        </React.Fragment>
                      ))}
                    </div>
                    <div className="cap" style={{ marginTop: 7 }}>Est. {x.budget} · {x.estTime}</div>
                  </button>
                );
              })}
            </div>
          </Field>

          {/* agent */}
          <Field label="Agent" hint="Auto picks the workflow's default.">
            <div style={{ display: "flex", gap: 8 }}>
              {["auto", "claude", "codex"].map(a => {
                const active = agent === a;
                const data = a === "auto" ? { name: "Auto", model: `→ ${w.model}` } : AGENTS[a];
                return (
                  <button key={a} onClick={() => setAgent(a)}
                    style={{ flex: 1, padding: "11px 8px", borderRadius: 11, cursor: "pointer", textAlign: "center", transition: "all .14s",
                      border: `1px solid ${active ? "var(--accent-ring)" : "var(--border)"}`, background: active ? "var(--accent-soft)" : "var(--surface-2)" }}>
                    <div style={{ fontSize: 13.5, fontWeight: 700, marginBottom: 3 }}>{a === "auto" ? "✨ Auto" : `${AGENTS[a].name}`}</div>
                    <div className="mono" style={{ fontSize: 9.5, color: "var(--text-3)" }}>{a === "auto" ? `→ ${w.model.replace("claude-", "").replace("gpt-5.1-", "")}` : AGENTS[a].model.replace("claude-", "").replace("gpt-5.1-", "")}</div>
                  </button>
                );
              })}
            </div>
          </Field>

          {/* branch */}
          <Field label="Branch" hint={<>Base <span className="mono" style={{ fontSize: 11 }}>main</span></>}>
            <div style={{ position: "relative" }}>
              <Icons.branch size={14} style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", color: "var(--text-3)" }} />
              <input className="input mono" value={branch} onChange={(e) => setBranch(e.target.value)} style={{ paddingLeft: 33, fontSize: 12 }} />
            </div>
          </Field>

          {/* advanced */}
          <div>
            <button onClick={() => setAdvanced(a => !a)} style={{ display: "flex", alignItems: "center", gap: 7, background: "transparent", border: 0, color: "var(--text-2)", cursor: "pointer", fontSize: 13, fontWeight: 600, fontFamily: "var(--font-ui)", padding: 0 }}>
              <Icons.chevR size={14} style={{ transform: advanced ? "rotate(90deg)" : "none", transition: "transform .15s" }} />Advanced guardrails
            </button>
            {advanced && (
              <div className="fade-in" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 14 }}>
                <MiniField label="Max budget ($)"><input className="input mono" placeholder={String(w.maxBudget)} value={budget} onChange={e => setBudget(e.target.value)} /></MiniField>
                <MiniField label="Max turns"><input className="input mono" defaultValue={w.maxTurns} /></MiniField>
                <MiniField label="Timeout (min)"><input className="input mono" defaultValue={w.timeout} /></MiniField>
                <MiniField label="Memory"><input className="input mono" defaultValue="8g" /></MiniField>
                <div style={{ gridColumn: "1 / -1" }}><MiniField label="Extra context files"><input className="input mono" placeholder="impl_docs/, ARCHITECTURE.md" /></MiniField></div>
              </div>
            )}
          </div>
        </div>

        {/* footer */}
        <div style={{ position: "sticky", bottom: 0, padding: "16px 22px", borderTop: "1px solid var(--border)", background: "var(--surface)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, padding: "9px 12px", background: "var(--surface-2)", borderRadius: 10 }}>
            <Icons.coin size={15} style={{ color: "var(--st-done)" }} />
            <span style={{ fontSize: 12.5, color: "var(--text-2)" }}>Est. <strong className="mono" style={{ color: "var(--text)" }}>{w.budget}</strong> · {w.estTime}{w.pauses ? <> · <span style={{ color: "var(--st-paused)", fontWeight: 600 }}>pauses once for you</span></> : ""}</span>
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <button className="btn btn-soft" style={{ flex: "none" }} onClick={onBack}>Queue for later</button>
            <button className="btn btn-primary" onClick={() => onLaunch({ wf, agent: resolvedAgent, branch })} style={{ flex: 1, justifyContent: "center", fontSize: 14.5 }}>
              <Icons.play size={16} />Run with {resolvedAgent === "claude" ? "Claude" : "Codex"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, hint, children }) {
  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 9 }}>
        <label style={{ fontSize: 13, fontWeight: 700 }}>{label}</label>
        {hint && <span className="cap">{hint}</span>}
      </div>
      {children}
    </div>
  );
}
function MiniField({ label, children }) {
  return <div><label className="cap" style={{ display: "block", marginBottom: 6, fontWeight: 600 }}>{label}</label>{children}</div>;
}

Object.assign(window, { IssueDetail });
