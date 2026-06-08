/* ============================================================
   DKMV — shared components & icons
   ============================================================ */
const { useState, useEffect, useRef, useMemo, useCallback } = React;

/* ---------- Icons (stroke, inherit currentColor) ---------- */
function Ico({ d, size = 18, fill, stroke = 2, children, vb = 24 }) {
  return (
    <svg width={size} height={size} viewBox={`0 0 ${vb} ${vb}`} fill={fill || "none"}
      stroke={fill ? "none" : "currentColor"} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
      {d ? <path d={d} /> : children}
    </svg>
  );
}
const Icons = {
  board:  (p) => <Ico {...p}><rect x="3" y="3" width="7" height="18" rx="1.5"/><rect x="14" y="3" width="7" height="11" rx="1.5"/></Ico>,
  runs:   (p) => <Ico {...p} d="M5 12h4l2-7 3 14 2-7h3"/>,
  flow:   (p) => <Ico {...p}><rect x="3" y="4" width="6" height="4" rx="1"/><rect x="15" y="9" width="6" height="4" rx="1"/><rect x="3" y="16" width="6" height="4" rx="1"/><path d="M9 6h3a2 2 0 0 1 2 2v0M9 18h3a2 2 0 0 0 2-2v-1"/></Ico>,
  settings:(p) => <Ico {...p}><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/></Ico>,
  plus:   (p) => <Ico {...p} d="M12 5v14M5 12h14"/>,
  search: (p) => <Ico {...p}><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></Ico>,
  refresh:(p) => <Ico {...p} d="M21 12a9 9 0 1 1-2.6-6.4M21 4v5h-5"/>,
  sun:    (p) => <Ico {...p}><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19"/></Ico>,
  moon:   (p) => <Ico {...p} d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/>,
  chevD:  (p) => <Ico {...p} d="m6 9 6 6 6-6"/>,
  chevR:  (p) => <Ico {...p} d="m9 6 6 6-6 6"/>,
  chevL:  (p) => <Ico {...p} d="m15 6-6 6 6 6"/>,
  dots:   (p) => <Ico {...p}><circle cx="5" cy="12" r="1.6" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1.6" fill="currentColor" stroke="none"/></Ico>,
  play:   (p) => <Ico {...p} fill="currentColor" d="M7 5.5v13l11-6.5z"/>,
  stop:   (p) => <Ico {...p}><rect x="6" y="6" width="12" height="12" rx="2.5" fill="currentColor" stroke="none"/></Ico>,
  pause:  (p) => <Ico {...p}><rect x="7" y="5" width="3.4" height="14" rx="1.2" fill="currentColor" stroke="none"/><rect x="13.6" y="5" width="3.4" height="14" rx="1.2" fill="currentColor" stroke="none"/></Ico>,
  check:  (p) => <Ico {...p} d="M20 6 9 17l-5-5"/>,
  x:      (p) => <Ico {...p} d="M18 6 6 18M6 6l12 12"/>,
  clock:  (p) => <Ico {...p}><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></Ico>,
  coin:   (p) => <Ico {...p}><circle cx="12" cy="12" r="9"/><path d="M12 7v10M14.5 9.3c-.5-.8-1.5-1.3-2.7-1.3-1.6 0-2.8.8-2.8 2s1 1.7 2.8 2 2.8.9 2.8 2-1.2 2-2.8 2c-1.2 0-2.2-.5-2.7-1.3"/></Ico>,
  token:  (p) => <Ico {...p}><circle cx="12" cy="12" r="9"/><path d="M8 12h8M12 8v8" /></Ico>,
  turn:   (p) => <Ico {...p} d="M3 12a9 9 0 1 1 9 9M3 12l3-3M3 12l3 3"/>,
  github: (p) => <Ico {...p} vb={24}><path fill="currentColor" stroke="none" d="M12 2C6.48 2 2 6.58 2 12.25c0 4.53 2.87 8.37 6.84 9.73.5.1.68-.22.68-.49l-.01-1.7c-2.78.62-3.37-1.22-3.37-1.22-.46-1.18-1.11-1.5-1.11-1.5-.91-.64.07-.62.07-.62 1 .07 1.53 1.06 1.53 1.06.9 1.57 2.36 1.12 2.94.85.09-.66.35-1.12.63-1.37-2.22-.26-4.56-1.14-4.56-5.07 0-1.12.39-2.03 1.03-2.75-.1-.26-.45-1.3.1-2.7 0 0 .84-.28 2.75 1.05a9.3 9.3 0 0 1 5 0c1.91-1.33 2.75-1.05 2.75-1.05.55 1.4.2 2.44.1 2.7.64.72 1.03 1.63 1.03 2.75 0 3.94-2.34 4.8-4.57 5.06.36.32.68.95.68 1.92l-.01 2.84c0 .27.18.59.69.49A10.03 10.03 0 0 0 22 12.25C22 6.58 17.52 2 12 2Z"/></Ico>,
  pr:     (p) => <Ico {...p}><circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M6 8.5v7M18 15.5V12a3 3 0 0 0-3-3h-3l2-2m0 4-2-2"/></Ico>,
  branch: (p) => <Ico {...p}><circle cx="6" cy="5" r="2.4"/><circle cx="6" cy="19" r="2.4"/><circle cx="18" cy="7" r="2.4"/><path d="M6 7.4v9.2M18 9.4c0 4-3 5-6 5"/></Ico>,
  file:   (p) => <Ico {...p}><path d="M14 3v5h5"/><path d="M6 3h8l5 5v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"/></Ico>,
  bolt:   (p) => <Ico {...p} fill="currentColor" d="M13 2 4 13h6l-1 9 9-11h-6z"/>,
  filter: (p) => <Ico {...p} d="M3 5h18l-7 8v5l-4 2v-7z"/>,
  grip:   (p) => <Ico {...p}><circle cx="9" cy="6" r="1.4" fill="currentColor" stroke="none"/><circle cx="15" cy="6" r="1.4" fill="currentColor" stroke="none"/><circle cx="9" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="15" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="9" cy="18" r="1.4" fill="currentColor" stroke="none"/><circle cx="15" cy="18" r="1.4" fill="currentColor" stroke="none"/></Ico>,
  ext:    (p) => <Ico {...p} d="M14 5h5v5M19 5l-8 8M12 5H7a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5"/>,
  spark:  (p) => <Ico {...p} d="M12 3v4M12 17v4M3 12h4M17 12h4M6.3 6.3l2.5 2.5M15.2 15.2l2.5 2.5M17.7 6.3l-2.5 2.5M8.8 15.2l-2.5 2.5"/>,
  arrowR: (p) => <Ico {...p} d="M5 12h14M13 6l6 6-6 6"/>,
  panel:  (p) => <Ico {...p}><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/></Ico>,
  list:   (p) => <Ico {...p} d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>,
  chart:  (p) => <Ico {...p} d="M4 19V5M4 19h16M8 19v-6M12 19v-9M16 19v-4M20 19V8"/>,
  warn:   (p) => <Ico {...p}><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.3 2.5 17a2 2 0 0 0 1.7 3h15.6a2 2 0 0 0 1.7-3L13.7 3.3a2 2 0 0 0-3.4 0Z"/></Ico>,
  code:   (p) => <Ico {...p} d="m9 8-4 4 4 4M15 8l4 4-4 4"/>,
  retry:  (p) => <Ico {...p} d="M3 12a9 9 0 1 0 3-6.7M3 4v4h4"/>,
};

const STATE_OF = {
  backlog: "queued", queued: "queued", progress: "running",
  needsyou: "paused", review: "review", done: "done",
  pending: "cancel", running: "running", paused: "paused",
  completed: "done", failed: "failed", cancelled: "cancel", timed_out: "failed",
};
const STATE_LABEL = {
  queued: "Queued", running: "Running", paused: "Needs you", review: "In review",
  done: "Done", failed: "Failed", cancel: "Cancelled",
  completed: "Completed", cancelled: "Cancelled", timed_out: "Timed out", pending: "Pending",
};

function StateBadge({ status, label, icon = true }) {
  const s = STATE_OF[status] || "queued";
  const Iconmap = { running: Icons.bolt, paused: Icons.pause, done: Icons.check, failed: Icons.x, review: Icons.pr, cancel: Icons.x, queued: Icons.clock };
  const I = Iconmap[s];
  return (
    <span className={`state s-${s}`}>
      <span className="dot"></span>
      {label || STATE_LABEL[status] || STATE_LABEL[s]}
    </span>
  );
}

function GhLabel({ name }) {
  const l = LABELS[name] || { name, color: "#888" };
  return <span className="gh-label" style={{ "--lc": l.color }}>{l.name}</span>;
}

function AgentChip({ id, withModel }) {
  if (!id || id === "auto") return <span className="badge badge-soft" style={{ fontSize: 11 }}>Auto</span>;
  const a = AGENTS[id];
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span style={{ width: 18, height: 18, borderRadius: 6, background: `color-mix(in oklab, ${a.color} 22%, transparent)`, color: a.color, display: "grid", placeItems: "center", fontSize: 10, fontWeight: 800, border: `1px solid color-mix(in oklab, ${a.color} 40%, transparent)` }}>{a.short}</span>
      <span style={{ fontSize: 12.5, fontWeight: 600 }}>{a.name}</span>
      {withModel && <span className="mono" style={{ fontSize: 11, color: "var(--text-3)" }}>{a.model}</span>}
    </span>
  );
}

function WfChip({ id }) {
  const w = WF[id];
  if (!w) return null;
  return <span className="badge badge-soft" style={{ paddingLeft: 7 }}><span style={{ fontSize: 12 }}>{w.emoji}</span>{w.name}</span>;
}

function Avatar({ initials, size = 26, color = "var(--accent)" }) {
  return <span style={{ width: size, height: size, borderRadius: 99, background: `linear-gradient(135deg, ${color}, color-mix(in oklab, ${color} 55%, #000))`, color: "#fff", display: "grid", placeItems: "center", fontSize: size * 0.4, fontWeight: 700, flex: "none", boxShadow: "var(--shadow-sm)" }}>{initials}</span>;
}

/* animated number that eases toward target */
function useTween(target, ms = 600) {
  const [v, setV] = useState(target);
  const ref = useRef({ from: target, start: 0, raf: 0, to: target, v: target });
  ref.current.v = v;
  useEffect(() => {
    const r = ref.current;
    r.from = r.v; r.to = target;
    if (Math.abs(target - r.from) < 0.001) { setV(target); return; }
    r.start = performance.now();
    cancelAnimationFrame(r.raf);
    const tick = (now) => {
      const p = Math.min(1, (now - r.start) / ms);
      const e = 1 - Math.pow(1 - p, 3);
      setV(p < 1 ? r.from + (target - r.from) * e : target);
      if (p < 1) r.raf = requestAnimationFrame(tick);
    };
    r.raf = requestAnimationFrame(tick);
    // fallback: if rAF is throttled (backgrounded iframe), still land on target
    const snap = setTimeout(() => setV(r.to), ms + 80);
    return () => { cancelAnimationFrame(r.raf); clearTimeout(snap); };
  }, [target, ms]);
  return v;
}

function Money({ value, className = "" }) {
  const v = useTween(value);
  return <span className={`mono ${className}`}>${v.toFixed(2)}</span>;
}
function Count({ value, className = "" }) {
  const v = useTween(value);
  return <span className={`mono ${className}`}>{Math.round(v).toLocaleString()}</span>;
}

/* Meter pill used in headers */
function Meter({ icon, label, children, accent }) {
  const I = icon;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 9, padding: "8px 13px", background: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: 12 }}>
      {I && <span style={{ color: accent || "var(--text-3)", display: "grid" }}><I size={16} /></span>}
      <div style={{ display: "flex", flexDirection: "column", gap: 1, lineHeight: 1.1 }}>
        <span style={{ fontSize: 15, fontWeight: 700 }}>{children}</span>
        <span className="cap">{label}</span>
      </div>
    </div>
  );
}

/* dropdown menu */
function Menu({ items, children, align = "right" }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <div onClick={(e) => { e.stopPropagation(); setOpen(o => !o); }}>{children}</div>
      {open && (
        <div className="card fade-in" style={{ position: "absolute", top: "calc(100% + 6px)", [align]: 0, minWidth: 184, padding: 6, zIndex: 60, boxShadow: "var(--shadow-lg)" }}>
          {items.map((it, i) => it.sep ? <hr key={i} className="divider" style={{ margin: "5px 4px" }} /> : (
            <button key={i} onClick={(e) => { e.stopPropagation(); setOpen(false); it.onClick && it.onClick(); }}
              style={{ display: "flex", alignItems: "center", gap: 10, width: "100%", textAlign: "left", padding: "8px 10px", borderRadius: 8, border: 0, background: "transparent", color: it.danger ? "var(--st-failed)" : "var(--text)", fontSize: 13, fontWeight: 500, cursor: "pointer", fontFamily: "var(--font-ui)" }}
              onMouseEnter={(e) => e.currentTarget.style.background = "var(--surface-2)"}
              onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}>
              {it.icon && <it.icon size={15} />}{it.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* segmented control */
function Segmented({ options, value, onChange, size = "md" }) {
  return (
    <div style={{ display: "inline-flex", background: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: 10, padding: 3, gap: 2 }}>
      {options.map(o => {
        const active = (o.value ?? o) === value;
        return (
          <button key={o.value ?? o} onClick={() => onChange(o.value ?? o)}
            style={{ padding: size === "sm" ? "4px 10px" : "6px 13px", fontSize: size === "sm" ? 12 : 13, fontWeight: 600, border: 0, borderRadius: 7, cursor: "pointer", fontFamily: "var(--font-ui)",
              background: active ? "var(--surface)" : "transparent", color: active ? "var(--text)" : "var(--text-3)",
              boxShadow: active ? "var(--shadow-sm)" : "none", transition: "all .15s var(--ease)", display: "inline-flex", alignItems: "center", gap: 6 }}>
            {o.icon && <o.icon size={14} />}{o.label ?? o}
          </button>
        );
      })}
    </div>
  );
}

/* ---------- Theme registry + picker ---------- */
const THEMES = [
  { id: "ember",     name: "Ember",     desc: "Warm coral",      accent: "#ff6b4a", bgD: "#16140f", bgL: "#f7f4ef" },
  { id: "indigo",    name: "Indigo",    desc: "Cool periwinkle", accent: "#7b7bf5", bgD: "#14131c", bgL: "#f3f3f9" },
  { id: "evergreen", name: "Evergreen", desc: "Calm emerald",    accent: "#18b88a", bgD: "#101713", bgL: "#eff5f1" },
  { id: "graphite",  name: "Graphite",  desc: "Minimal azure",   accent: "#5d8bf0", bgD: "#131417", bgL: "#f4f5f6" },
  { id: "plum",      name: "Plum",      desc: "Premium orchid",  accent: "#d563c9", bgD: "#181219", bgL: "#f8f2f8" },
  { id: "rose",      name: "Rose",      desc: "Soft punch",      accent: "#fb6f7a", bgD: "#181011", bgL: "#f9f2f2" },
];

function ThemePicker({ skin, setSkin, mode }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);
  const cur = THEMES.find(t => t.id === skin) || THEMES[0];
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button className="btn btn-soft" onClick={() => setOpen(o => !o)} title="Theme" style={{ padding: "7px 11px 7px 9px", gap: 7 }}>
        <span style={{ width: 16, height: 16, borderRadius: 5, background: `linear-gradient(135deg, ${cur.accent}, color-mix(in oklab, ${cur.accent} 55%, #000))`, flex: "none", boxShadow: "inset 0 0 0 1px rgba(255,255,255,.18)" }} />
        <span style={{ fontSize: 13, fontWeight: 600 }}>{cur.name}</span>
        <Icons.chevD size={14} style={{ color: "var(--text-3)" }} />
      </button>
      {open && (
        <div className="card fade-in" style={{ position: "absolute", top: "calc(100% + 8px)", right: 0, width: 256, padding: 8, zIndex: 80, boxShadow: "var(--shadow-lg)" }}>
          <div className="cap" style={{ padding: "4px 8px 8px", fontWeight: 700, textTransform: "uppercase", letterSpacing: ".06em", fontSize: 10 }}>Theme</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
            {THEMES.map(t => {
              const active = t.id === skin;
              const bg = mode === "light" ? t.bgL : t.bgD;
              return (
                <button key={t.id} onClick={() => { setSkin(t.id); setOpen(false); }}
                  style={{ display: "flex", flexDirection: "column", gap: 8, padding: 10, borderRadius: 11, cursor: "pointer", textAlign: "left",
                    border: `1px solid ${active ? "var(--accent-ring)" : "var(--border)"}`, background: active ? "var(--accent-soft)" : "var(--surface-2)", transition: "all .12s" }}>
                  <span style={{ height: 30, borderRadius: 7, background: bg, border: "1px solid var(--border)", position: "relative", overflow: "hidden", display: "flex", alignItems: "center", paddingLeft: 8, gap: 5 }}>
                    <span style={{ width: 14, height: 14, borderRadius: 4, background: `linear-gradient(135deg, ${t.accent}, color-mix(in oklab, ${t.accent} 55%, #000))` }} />
                    <span style={{ width: 26, height: 5, borderRadius: 9, background: "color-mix(in oklab, " + t.accent + " 30%, transparent)" }} />
                  </span>
                  <span style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <span style={{ fontSize: 12.5, fontWeight: 700 }}>{t.name}</span>
                    {active && <Icons.check size={13} style={{ color: "var(--accent)" }} />}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

Object.assign(window, {
  Ico, Icons, StateBadge, GhLabel, AgentChip, WfChip, Avatar,
  useTween, Money, Count, Meter, Menu, Segmented, STATE_OF, STATE_LABEL,
  THEMES, ThemePicker,
});
