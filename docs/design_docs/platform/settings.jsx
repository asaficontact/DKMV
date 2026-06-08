/* ============================================================
   DKMV — Settings (preflight, integrations)
   ============================================================ */
function SettingsScreen({ go }) {
  return (
    <div style={{ overflowY: "auto", height: "100%", padding: "26px 28px 60px" }}>
      <div style={{ maxWidth: 680, margin: "0 auto" }}>
        <h1 style={{ margin: "0 0 4px", fontSize: 22, fontWeight: 800, letterSpacing: "-.02em" }}>Settings</h1>
        <p style={{ margin: "0 0 26px", color: "var(--text-2)", fontSize: 14 }}>Connections and sandbox preflight for <span className="mono" style={{ fontSize: 12.5 }}>asaficontact/DKMV</span>.</p>

        <SettingsSection title="Preflight" sub="Everything DKMV needs before a run">
          {PREFLIGHT.map(p => (
            <div key={p.id} style={{ display: "flex", alignItems: "center", gap: 13, padding: "13px 0", borderBottom: "1px solid color-mix(in oklab, var(--border) 60%, transparent)" }}>
              <span style={{ width: 30, height: 30, borderRadius: 9, background: "color-mix(in oklab, var(--st-done) 14%, transparent)", color: "var(--st-done)", display: "grid", placeItems: "center", flex: "none" }}><Icons.check size={16} /></span>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13.5, fontWeight: 700 }}>{p.label}</div>
                <div className="mono cap" style={{ marginTop: 1 }}>{p.sub}</div>
              </div>
              <span className="state s-done"><span className="dot" />Ready</span>
            </div>
          ))}
        </SettingsSection>

        <SettingsSection title="GitHub" sub="The connected account & active repository">
          <div style={{ display: "flex", alignItems: "center", gap: 13, padding: "6px 0" }}>
            <Avatar initials="AS" size={40} />
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 14, fontWeight: 700 }}>asaficontact</div>
              <div className="cap">Connected · read issues, write <span className="mono" style={{ fontSize: 11 }}>agent:*</span> labels</div>
            </div>
            <button className="btn btn-soft" onClick={() => go("connect")}><Icons.refresh size={14} />Switch repo</button>
          </div>
        </SettingsSection>

        <SettingsSection title="Defaults" sub="Applied to new runs unless overridden">
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
            <DefField label="Default agent"><div className="input" style={{ display: "flex", alignItems: "center", height: 38 }}><AgentChip id="claude" /></div></DefField>
            <DefField label="Default memory"><input className="input mono" defaultValue="8g" /></DefField>
            <DefField label="Default timeout"><input className="input mono" defaultValue="30m" /></DefField>
            <DefField label="Spend alert at"><input className="input mono" defaultValue="$25.00 / day" /></DefField>
          </div>
        </SettingsSection>
      </div>
    </div>
  );
}
function SettingsSection({ title, sub, children }) {
  return (
    <div className="card" style={{ padding: "18px 20px", marginBottom: 16 }}>
      <div style={{ marginBottom: 12 }}>
        <h3 style={{ margin: "0 0 2px", fontSize: 15, fontWeight: 800 }}>{title}</h3>
        <p className="cap" style={{ margin: 0 }}>{sub}</p>
      </div>
      {children}
    </div>
  );
}
Object.assign(window, { SettingsScreen });
