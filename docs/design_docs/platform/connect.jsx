/* ============================================================
   DKMV — Screen A: Connect & project picker (full-screen)
   ============================================================ */

function Connect({ mode, setMode, skin, setSkin, state, setState, onDone }) {
  // state: disconnected | connecting | picker | syncing
  const [selected, setSelected] = useState(null);
  const [query, setQuery] = useState("");

  const connect = () => { setState("connecting"); setTimeout(() => setState("picker"), 1400); };
  const openProject = () => { setState("syncing"); setTimeout(() => onDone(), 1800); };

  const repos = REPOS.filter(r => `${r.org}/${r.name} ${r.lang}`.toLowerCase().includes(query.toLowerCase()));

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column", background: "radial-gradient(1200px 600px at 50% -5%, var(--bg-grad-a), var(--bg-grad-b))", overflow: "auto" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "20px 28px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
          <Logo size={32} />
          <span style={{ fontSize: 19, fontWeight: 800, letterSpacing: "-.02em" }}>DKMV</span>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <Segmented size="sm" options={[{ value: "disconnected", label: "Welcome" }, { value: "picker", label: "Pick repo" }, { value: "syncing", label: "Syncing" }]} value={state === "connecting" ? "disconnected" : state} onChange={setState} />
          <ThemePicker skin={skin} setSkin={setSkin} mode={mode} />
          <button className="btn btn-soft btn-icon" onClick={() => setMode(mode === "dark" ? "light" : "dark")}>{mode === "dark" ? <Icons.sun size={16} /> : <Icons.moon size={16} />}</button>
        </div>
      </div>

      <div style={{ flex: 1, display: "grid", placeItems: "center", padding: "20px 28px 60px" }}>
        {(state === "disconnected" || state === "connecting") && (
          <div className="fade-in" style={{ maxWidth: 540, textAlign: "center" }}>
            <div style={{ width: 96, height: 96, margin: "0 auto 28px", borderRadius: 26, background: "linear-gradient(140deg, var(--accent-hover), var(--accent-press))", display: "grid", placeItems: "center", boxShadow: "0 18px 50px -14px color-mix(in oklab, var(--accent) 70%, transparent)" }}>
              <Icons.github size={46} style={{ color: "#fff" }} />
            </div>
            <h1 style={{ margin: "0 0 14px", fontSize: 34, fontWeight: 800, letterSpacing: "-.03em", lineHeight: 1.1 }}>Turn your GitHub issues<br />into work that runs itself.</h1>
            <p style={{ margin: "0 auto 30px", color: "var(--text-2)", fontSize: 16, lineHeight: 1.6, maxWidth: 440 }}>
              Connect a repo, assign each issue a workflow and an agent, and press Run. DKMV opens a sandbox, does the work, and brings back a pull request — while you watch.
            </p>
            <button className="btn btn-primary btn-lg" onClick={connect} disabled={state === "connecting"} style={{ fontSize: 16, padding: "15px 28px" }}>
              {state === "connecting" ? <><Icons.refresh size={18} className="spin" />Connecting to GitHub…</> : <><Icons.github size={19} />Connect GitHub</>}
            </button>
            <p className="cap" style={{ marginTop: 18, display: "flex", gap: 7, justifyContent: "center", alignItems: "center" }}>
              <Icons.check size={13} style={{ color: "var(--st-done)" }} />
              Read-only on your code. We only read issues and add <span className="mono" style={{ fontSize: 11.5 }}>agent:*</span> labels. Nothing runs until you say so.
            </p>
          </div>
        )}

        {state === "picker" && (
          <div className="fade-in" style={{ width: "100%", maxWidth: 860, display: "grid", gridTemplateColumns: selected ? "1fr 340px" : "1fr", gap: 20, alignItems: "start" }}>
            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
              <div style={{ padding: "18px 20px 14px", borderBottom: "1px solid var(--border)" }}>
                <h2 style={{ margin: "0 0 4px", fontSize: 19, fontWeight: 800, letterSpacing: "-.02em" }}>Choose a repository</h2>
                <p style={{ margin: "0 0 14px", color: "var(--text-2)", fontSize: 13.5 }}>One project at a time. You can switch any time from the sidebar.</p>
                <div style={{ position: "relative" }}>
                  <Icons.search size={15} style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--text-3)" }} />
                  <input className="input" autoFocus placeholder="Search repositories…" value={query} onChange={(e) => setQuery(e.target.value)} style={{ paddingLeft: 35 }} />
                </div>
              </div>
              <div style={{ maxHeight: 360, overflowY: "auto", padding: 8 }}>
                {repos.map(r => {
                  const active = selected?.name === r.name && selected?.org === r.org;
                  return (
                    <button key={`${r.org}/${r.name}`} onClick={() => setSelected(r)}
                      style={{ display: "flex", alignItems: "center", gap: 13, width: "100%", textAlign: "left", padding: "12px 13px", borderRadius: 11, border: `1px solid ${active ? "var(--accent-ring)" : "transparent"}`, background: active ? "var(--accent-soft)" : "transparent", cursor: "pointer", marginBottom: 2, transition: "all .12s" }}
                      onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = "var(--surface-2)"; }}
                      onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = "transparent"; }}>
                      <Avatar initials={r.org.slice(0, 2).toUpperCase()} size={34} color={active ? "var(--accent)" : "var(--st-review)"} />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{ fontSize: 14, fontWeight: 700 }}><span style={{ color: "var(--text-3)", fontWeight: 500 }}>{r.org}/</span>{r.name}</span>
                          <span className="gh-label" style={{ "--lc": r.private ? "var(--st-paused)" : "var(--st-done)", fontSize: 10 }}>{r.private ? "private" : "public"}</span>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 3 }} className="cap">
                          <span style={{ display: "flex", alignItems: "center", gap: 5 }}><span style={{ width: 9, height: 9, borderRadius: 99, background: r.langColor }} />{r.lang}</span>
                          <span>{r.issues} open issues</span>
                          <span>{r.updated}</span>
                        </div>
                      </div>
                      {active && <Icons.check size={18} style={{ color: "var(--accent)" }} />}
                    </button>
                  );
                })}
              </div>
            </div>

            {selected && (
              <div className="card slide-in" style={{ padding: 20, position: "sticky", top: 0 }}>
                <h3 style={{ margin: "0 0 12px", fontSize: 15, fontWeight: 800 }}>What we'll do</h3>
                <div style={{ display: "flex", flexDirection: "column", gap: 11, marginBottom: 16 }}>
                  <ConfirmRow ok text={<>Read issues from <span className="mono" style={{ fontSize: 12 }}>{selected.org}/{selected.name}</span></>} />
                  <ConfirmRow ok text={<>Add <span className="mono" style={{ fontSize: 12 }}>agent:*</span> labels to track work</>} />
                  <ConfirmRow ok text="Nothing runs until you press Run" />
                </div>
                <div style={{ background: "var(--surface-2)", borderRadius: 11, padding: "12px 14px", marginBottom: 16 }}>
                  <div className="cap" style={{ marginBottom: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".06em", fontSize: 10 }}>Preflight</div>
                  {PREFLIGHT.map(p => (
                    <div key={p.id} style={{ display: "flex", alignItems: "center", gap: 9, padding: "4px 0" }}>
                      <span style={{ width: 18, height: 18, borderRadius: 6, background: "color-mix(in oklab, var(--st-done) 16%, transparent)", color: "var(--st-done)", display: "grid", placeItems: "center", flex: "none" }}><Icons.check size={12} /></span>
                      <span style={{ fontSize: 12.5, fontWeight: 600 }}>{p.label}</span>
                      <span className="mono" style={{ fontSize: 10.5, color: "var(--text-3)", marginLeft: "auto" }}>{p.sub}</span>
                    </div>
                  ))}
                </div>
                <button className="btn btn-primary" onClick={openProject} style={{ width: "100%", justifyContent: "center" }}>Open project<Icons.arrowR size={16} /></button>
              </div>
            )}
          </div>
        )}

        {state === "syncing" && (
          <div className="fade-in" style={{ textAlign: "center", maxWidth: 400 }}>
            <div style={{ width: 80, height: 80, margin: "0 auto 24px", borderRadius: 22, background: "var(--accent-soft)", display: "grid", placeItems: "center", color: "var(--accent)" }}>
              <Icons.refresh size={38} className="spin" />
            </div>
            <h2 style={{ margin: "0 0 10px", fontSize: 22, fontWeight: 800 }}>Importing your issues…</h2>
            <p style={{ margin: "0 0 20px", color: "var(--text-2)", fontSize: 14.5 }}>Reading <span className="mono" style={{ fontSize: 13 }}>asaficontact/DKMV</span> and mapping labels to your board.</p>
            <div style={{ maxWidth: 260, margin: "0 auto" }}><div className="run-bar" /></div>
          </div>
        )}
      </div>
    </div>
  );
}

function ConfirmRow({ ok, text }) {
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
      <span style={{ width: 20, height: 20, borderRadius: 7, background: "color-mix(in oklab, var(--st-done) 16%, transparent)", color: "var(--st-done)", display: "grid", placeItems: "center", flex: "none", marginTop: 1 }}><Icons.check size={13} /></span>
      <span style={{ fontSize: 13, color: "var(--text-2)", lineHeight: 1.45 }}>{text}</span>
    </div>
  );
}

Object.assign(window, { Connect });
