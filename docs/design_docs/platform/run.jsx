/* ============================================================
   DKMV — Screen D: Live run / session view
   ============================================================ */

function LiveRun({ runId, issue, state, setState, onBack, onGoBoard }) {
  // state: running | paused | completed | failed
  const [events, setEvents] = useState(RUN_EVENTS);
  const [cost, setCost] = useState(4.18);
  const [turns, setTurns] = useState(37);
  const [tokIn, setTokIn] = useState(71200);
  const [tokOut, setTokOut] = useState(18400);
  const [elapsed, setElapsed] = useState(155);
  const [progress, setProgress] = useState(0.62);
  const [raw, setRaw] = useState(false);
  const [railOpen, setRailOpen] = useState(true);
  const [filter, setFilter] = useState("");
  const [answered, setAnswered] = useState(null);
  const tailRef = useRef(0);
  const feedRef = useRef(null);

  const run = RUNS.find(r => r.id === runId) || RUNS[0];
  const isLive = state === "running";

  // reset meters per state
  useEffect(() => {
    if (state === "completed") { setCost(13.28); setTurns(153); setTokIn(184600); setTokOut(52300); setElapsed(2611); setProgress(1); setEvents([...RUN_EVENTS, ...STREAM_TAIL.map((e, i) => ({ ...e, t: fmtT(160 + i * 18), turn: 20 + i * 2 })), { kind: "result", icon: "✓", text: "Done · 153 turns · $13.28 · 43m 32s", t: "43:32", turn: 153 }]); }
    else if (state === "failed") { setCost(3.21); setTurns(48); setElapsed(940); setProgress(0.5); setTokIn(52100); setTokOut(11200); }
    else if (state === "paused") { setCost(6.40); setTurns(64); setElapsed(720); setProgress(0.4); setTokIn(98400); setTokOut(27100); setEvents(RUN_EVENTS.slice(0, 6)); }
    else { setCost(4.18); setTurns(37); setElapsed(155); setProgress(0.62); setTokIn(71200); setTokOut(18400); setEvents(RUN_EVENTS); tailRef.current = 0; }
  }, [state]);

  // live ticking
  useEffect(() => {
    if (!isLive) return;
    const meter = setInterval(() => {
      setCost(c => +(c + 0.03 + Math.random() * 0.04).toFixed(2));
      setElapsed(e => e + 1);
      setTokIn(t => t + Math.floor(120 + Math.random() * 200));
      setTokOut(t => t + Math.floor(30 + Math.random() * 80));
      setProgress(p => Math.min(0.97, p + 0.003));
    }, 1000);
    return () => clearInterval(meter);
  }, [isLive]);

  // stream new events
  useEffect(() => {
    if (!isLive) return;
    const streamer = setInterval(() => {
      if (tailRef.current >= STREAM_TAIL.length) { tailRef.current = 0; return; }
      const e = STREAM_TAIL[tailRef.current];
      tailRef.current++;
      setEvents(prev => [...prev, { ...e, t: fmtT(elapsedRef.current), turn: prev[prev.length - 1].turn + 2 }]);
      if (e.kind === "tool" || e.kind === "assistant") setTurns(t => t + 2);
    }, 2600);
    return () => clearInterval(streamer);
  }, [isLive]);
  const elapsedRef = useRef(elapsed);
  useEffect(() => { elapsedRef.current = elapsed; }, [elapsed]);

  // autoscroll
  useEffect(() => { if (feedRef.current && isLive) feedRef.current.scrollTop = feedRef.current.scrollHeight; }, [events, isLive]);

  const filteredEvents = filter ? events.filter(e => e.text.toLowerCase().includes(filter.toLowerCase())) : events;
  const statusMap = { running: "running", paused: "paused", completed: "completed", failed: "failed" };

  const answerPause = (label, skip) => {
    setAnswered({ label, skip });
    setEvents(prev => [...prev, { kind: "decision", icon: "✅", text: `You chose: "${label}"${skip ? " · skip remaining" : ""}`, t: fmtT(elapsed), turn: turns + 1 }]);
    setTimeout(() => { setState(skip ? "completed" : "running"); }, 700);
  };

  return (
    <div style={{ display: "flex", height: "100%", minHeight: 0 }}>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {/* run header */}
        <div style={{ padding: "18px 24px 14px", borderBottom: "1px solid var(--border)", flex: "none" }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 14, justifyContent: "space-between" }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 7, flexWrap: "wrap" }}>
                <RunStatusBadge state={state} />
                <span className="mono" style={{ fontSize: 11.5, color: "var(--text-3)" }}>{runId}</span>
              </div>
              <h1 style={{ margin: "0 0 8px", fontSize: 19, fontWeight: 800, letterSpacing: "-.02em", lineHeight: 1.3 }}>
                <span className="mono" style={{ fontSize: 15, color: "var(--text-3)", fontWeight: 600 }}>#{issue?.num || run.issue} </span>
                {issue?.title || run.issueTitle}
              </h1>
              <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", fontSize: 12.5, color: "var(--text-2)" }}>
                <span style={{ display: "flex", alignItems: "center", gap: 6 }}><WfChip id={run.wf} /></span>
                <AgentChip id={run.agent} withModel />
                <span style={{ display: "flex", alignItems: "center", gap: 5 }}><Icons.branch size={13} /><span className="mono" style={{ fontSize: 11.5 }}>{run.branch}</span></span>
              </div>
            </div>
            <div style={{ display: "flex", gap: 9, flex: "none" }}>
              {isLive && <Menu items={[{ label: "Attach terminal", icon: Icons.code, onClick: () => {} }, { label: "Keep alive on finish", icon: Icons.clock, onClick: () => {} }]}><button className="btn btn-soft btn-icon"><Icons.dots size={17} /></button></Menu>}
              {(state === "running" || state === "paused") && <button className="btn btn-danger"><Icons.stop size={15} />Stop</button>}
              {state === "failed" && <button className="btn btn-primary"><Icons.retry size={15} />Retry run</button>}
              {state === "completed" && run.pr && <button className="btn btn-primary"><Icons.pr size={15} />View PR #{run.pr}</button>}
            </div>
          </div>
        </div>

        {/* meters */}
        <div style={{ padding: "14px 24px", display: "flex", gap: 12, flexWrap: "wrap", flex: "none", alignItems: "center" }}>
          <Meter icon={Icons.clock} label="elapsed">{fmtClock(elapsed)}</Meter>
          <Meter icon={Icons.coin} label="cost" accent={isLive ? "var(--st-running)" : undefined}><Money value={cost} /></Meter>
          <Meter icon={Icons.token} label="tokens (in · out)"><span className="mono"><Count value={tokIn} /> · <Count value={tokOut} /></span></Meter>
          <Meter icon={Icons.turn} label="turns"><Count value={turns} /></Meter>
          <div style={{ flex: 1, minWidth: 160, display: "flex", flexDirection: "column", gap: 6, padding: "8px 4px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5 }}><span className="cap">overall progress</span><span className="mono" style={{ fontWeight: 700 }}>{Math.round(progress * 100)}%</span></div>
            <div style={{ height: 7, borderRadius: 99, background: "var(--surface-3)", overflow: "hidden" }}>
              <div style={{ height: "100%", width: `${progress * 100}%`, borderRadius: 99, background: state === "failed" ? "var(--st-failed)" : state === "completed" ? "var(--st-done)" : "linear-gradient(90deg, var(--st-running), color-mix(in oklab, var(--st-running) 60%, var(--accent)))", transition: "width .6s var(--ease)", position: "relative", overflow: "hidden" }}>
                {isLive && <span style={{ position: "absolute", inset: 0, background: "linear-gradient(90deg, transparent, rgba(255,255,255,.35), transparent)", animation: "runslide 1.6s infinite" }} />}
              </div>
            </div>
          </div>
          <button className="btn btn-ghost btn-icon" onClick={() => setRailOpen(o => !o)} title="Toggle details" style={{ marginLeft: "auto" }}><Icons.panel size={17} style={{ color: railOpen ? "var(--accent)" : "var(--text-3)" }} /></button>
        </div>
        <hr className="divider" />

        {/* stage tracker */}
        <StageTracker state={state} />

        {/* pause / completed / failed banners + feed */}
        <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", padding: "0 24px 0" }}>
          {state === "paused" && !answered && <PauseCard onAnswer={answerPause} />}
          {state === "completed" && <CompletedBanner run={run} onGoBoard={onGoBoard} />}
          {state === "failed" && <FailedBanner run={run} onRetry={() => setState("running")} />}

          {/* feed header */}
          <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "16px 0 12px", flex: "none" }}>
            <h3 style={{ margin: 0, fontSize: 13.5, fontWeight: 800, display: "flex", alignItems: "center", gap: 8 }}>
              Event stream
              {isLive && <span style={{ width: 7, height: 7, borderRadius: 99, background: "var(--st-running)", animation: "pulse-dot 1.4s infinite", "--c": "var(--st-running)" }} />}
            </h3>
            <div style={{ position: "relative", width: 200 }}>
              <Icons.search size={13} style={{ position: "absolute", left: 9, top: "50%", transform: "translateY(-50%)", color: "var(--text-3)" }} />
              <input className="input" placeholder="Filter events…" value={filter} onChange={e => setFilter(e.target.value)} style={{ paddingLeft: 28, height: 32, fontSize: 12.5 }} />
            </div>
            <div style={{ marginLeft: "auto" }}>
              <Segmented size="sm" options={[{ value: false, label: "Friendly", icon: Icons.spark }, { value: true, label: "Raw", icon: Icons.code }]} value={raw} onChange={setRaw} />
            </div>
          </div>

          {/* feed */}
          <div ref={feedRef} style={{ flex: 1, minHeight: 0, overflowY: "auto", paddingBottom: 20, fontFamily: raw ? "var(--font-mono)" : "var(--font-ui)" }}>
            {raw ? <RawFeed events={filteredEvents} /> : (
              <div style={{ display: "flex", flexDirection: "column" }}>
                {filteredEvents.map((e, i) => <EventRow key={i} e={e} last={i === filteredEvents.length - 1 && isLive} />)}
                {isLive && <ThinkingRow />}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* right rail */}
      {railOpen && <RunRail run={run} state={state} />}
    </div>
  );
}

/* ---------- sub-components ---------- */
function RunStatusBadge({ state }) {
  const map = { running: ["running", "Running", Icons.bolt], paused: ["paused", "Paused · needs you", Icons.pause], completed: ["done", "Completed", Icons.check], failed: ["failed", "Failed", Icons.x] };
  const [cls, label, I] = map[state];
  return <span className={`state s-${cls}`} style={{ fontSize: 12.5, padding: "5px 12px 5px 10px" }}><span className="dot" /><I size={12} />{label}</span>;
}

function EventRow({ e, last }) {
  const colorMap = { system: "var(--text-3)", assistant: "var(--text-2)", tool: "var(--st-running)", ok: "var(--st-done)", error: "var(--st-failed)", decision: "var(--st-done)", result: "var(--st-done)" };
  const c = colorMap[e.kind] || "var(--text-2)";
  const isText = e.kind === "assistant";
  return (
    <div className={last ? "fade-in" : ""} style={{ display: "flex", gap: 12, padding: "8px 0", borderBottom: "1px solid color-mix(in oklab, var(--border) 50%, transparent)", alignItems: "flex-start" }}>
      <span className="mono" style={{ fontSize: 10.5, color: "var(--text-3)", width: 42, flex: "none", paddingTop: 2, textAlign: "right" }}>{e.t}</span>
      <span style={{ fontSize: 14, flex: "none", width: 18, textAlign: "center", paddingTop: 1, filter: e.kind === "error" ? "none" : "none" }}>{e.icon}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: isText ? 13.5 : 13, color: e.kind === "error" ? "var(--st-failed)" : isText ? "var(--text)" : "var(--text-2)", lineHeight: 1.5, fontStyle: isText ? "normal" : "normal" }}>
          <FmtEvent text={e.text} kind={e.kind} />
        </div>
        {(e.kind === "decision") && <div style={{ marginTop: 4, height: 2, width: 40, background: "var(--st-done)", borderRadius: 9 }} />}
      </div>
      {e.tool && <span className="mono badge badge-soft" style={{ fontSize: 9.5, flex: "none", padding: "1px 6px" }}>{e.tool}</span>}
    </div>
  );
}
function FmtEvent({ text, kind }) {
  // highlight `code` spans
  const parts = text.split(/(`[^`]+`)/g);
  return parts.map((p, i) => p.startsWith("`")
    ? <code key={i} className="mono" style={{ fontSize: 12, background: "var(--surface-2)", padding: "1px 5px", borderRadius: 4, color: kind === "error" ? "var(--st-failed)" : "var(--text)", border: "1px solid var(--border)" }}>{p.slice(1, -1)}</code>
    : <span key={i}>{p}</span>);
}
function ThinkingRow() {
  return (
    <div className="fade-in" style={{ display: "flex", gap: 12, padding: "10px 0", alignItems: "center" }}>
      <span className="mono" style={{ fontSize: 10.5, color: "var(--text-3)", width: 42, flex: "none", textAlign: "right" }}>···</span>
      <span style={{ width: 18, flex: "none", display: "flex", justifyContent: "center", gap: 3 }}>
        {[0, 1, 2].map(i => <span key={i} style={{ width: 4, height: 4, borderRadius: 99, background: "var(--st-running)", animation: `bounce 1.2s ${i * 0.15}s infinite` }} />)}
      </span>
      <span style={{ fontSize: 13, color: "var(--text-3)", fontStyle: "italic" }}>agent working…</span>
    </div>
  );
}

function RawFeed({ events }) {
  return (
    <div style={{ fontSize: 11.5, lineHeight: 1.6 }}>
      {events.map((e, i) => {
        const obj = { type: e.kind === "tool" ? "assistant" : e.kind === "ok" || e.kind === "error" ? "user" : e.kind === "result" ? "result" : e.kind, subtype: e.kind === "tool" ? "tool_use" : e.kind === "assistant" ? "text" : "tool_result", content: e.text, tool_name: e.tool || null, is_error: e.kind === "error", num_turns: e.turn };
        return (
          <div key={i} style={{ padding: "3px 0", color: e.kind === "error" ? "var(--st-failed)" : "var(--text-2)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            <span style={{ color: "var(--text-3)" }}>{"{"}</span>
            <span style={{ color: "var(--st-review)" }}>"type"</span>: <span style={{ color: "var(--st-done)" }}>"{obj.type}"</span>, <span style={{ color: "var(--st-review)" }}>"subtype"</span>: <span style={{ color: "var(--st-done)" }}>"{obj.subtype}"</span>, <span style={{ color: "var(--st-review)" }}>"content"</span>: <span style={{ color: "var(--text)" }}>"{obj.content}"</span>{obj.tool_name ? <>, <span style={{ color: "var(--st-review)" }}>"tool_name"</span>: <span style={{ color: "var(--st-done)" }}>"{obj.tool_name}"</span></> : ""}, <span style={{ color: "var(--st-review)" }}>"num_turns"</span>: <span style={{ color: "var(--st-paused)" }}>{obj.num_turns}</span>
            <span style={{ color: "var(--text-3)" }}>{"}"}</span>
          </div>
        );
      })}
    </div>
  );
}

function StageTracker({ state }) {
  const stages = state === "paused"
    ? [{ name: "Analyze", status: "done", cost: 6.40, turns: 64, dur: "12m 00s" }, { name: "Features & Stories", status: "paused", cost: null, turns: null, dur: null }, { name: "Phases", status: "pending" }, { name: "Assembly", status: "pending" }, { name: "Evaluate-Fix", status: "pending" }]
    : state === "completed"
      ? RUN_STAGES.map((s, i) => ({ ...s, status: "done", cost: s.cost || 2.1 + i, dur: s.dur || "8m 12s", turns: s.turns || 30 }))
      : RUN_STAGES;
  const [open, setOpen] = useState(null);
  return (
    <div style={{ padding: "14px 24px", flex: "none", borderBottom: "1px solid var(--border)" }}>
      <div style={{ display: "flex", alignItems: "stretch", gap: 0 }}>
        {stages.map((s, i) => {
          const icon = { done: <Icons.check size={13} />, running: <span style={{ width: 7, height: 7, borderRadius: 99, background: "#fff" }} />, paused: <Icons.pause size={11} />, pending: <span style={{ width: 6, height: 6, borderRadius: 99, border: "1.5px solid var(--text-3)" }} /> }[s.status];
          const col = { done: "var(--st-done)", running: "var(--st-running)", paused: "var(--st-paused)", pending: "var(--text-3)" }[s.status];
          return (
            <React.Fragment key={i}>
              <button onClick={() => s.status !== "pending" && setOpen(open === i ? null : i)} style={{ display: "flex", flexDirection: "column", gap: 7, alignItems: "flex-start", background: "transparent", border: 0, cursor: s.status !== "pending" ? "pointer" : "default", padding: "2px 4px", flex: "none", maxWidth: 150 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ width: 22, height: 22, borderRadius: 99, display: "grid", placeItems: "center", flex: "none", background: s.status === "pending" ? "transparent" : `color-mix(in oklab, ${col} ${s.status === "running" ? "100%" : "18%"}, transparent)`, color: s.status === "running" ? "#fff" : col, border: s.status === "pending" ? "1.5px dashed var(--border-2)" : "none", boxShadow: s.status === "running" ? `0 0 0 4px color-mix(in oklab, ${col} 20%, transparent)` : "none" }}>{icon}</span>
                  <span style={{ fontSize: 12.5, fontWeight: s.status === "running" || s.status === "paused" ? 700 : 600, color: s.status === "pending" ? "var(--text-3)" : "var(--text)", textAlign: "left", lineHeight: 1.2 }}>{s.name}</span>
                </div>
                {s.cost != null && <span className="mono cap" style={{ paddingLeft: 30, fontSize: 10.5 }}>${s.cost.toFixed(2)} · {s.turns}t{s.dur ? ` · ${s.dur}` : ""}</span>}
                {s.status === "running" && <span className="cap" style={{ paddingLeft: 30, color: "var(--st-running)", fontWeight: 600 }}>in progress…</span>}
                {s.status === "paused" && <span className="cap" style={{ paddingLeft: 30, color: "var(--st-paused)", fontWeight: 600 }}>paused</span>}
              </button>
              {i < stages.length - 1 && <div style={{ flex: 1, minWidth: 16, height: 2, background: stages[i + 1].status !== "pending" || s.status === "done" ? "color-mix(in oklab, var(--st-done) 40%, var(--border))" : "var(--border)", alignSelf: "flex-start", marginTop: 12, borderRadius: 9 }} />}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
}

function PauseCard({ onAnswer }) {
  const q = PAUSE_REQUEST.questions[0];
  const [choice, setChoice] = useState(q.default);
  return (
    <div className="fade-in" style={{ margin: "18px 0 4px", flex: "none", borderRadius: 16, border: "1px solid color-mix(in oklab, var(--st-paused) 45%, transparent)", background: "color-mix(in oklab, var(--st-paused) 9%, var(--surface))", overflow: "hidden", boxShadow: "0 0 0 1px color-mix(in oklab, var(--st-paused) 18%, transparent), var(--shadow-md)" }}>
      <div style={{ padding: "16px 20px 14px", display: "flex", gap: 13, alignItems: "flex-start" }}>
        <span style={{ width: 38, height: 38, borderRadius: 11, background: "color-mix(in oklab, var(--st-paused) 20%, transparent)", color: "var(--st-paused)", display: "grid", placeItems: "center", flex: "none" }}><Icons.pause size={18} /></span>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <span className="badge" style={{ background: "color-mix(in oklab, var(--st-paused) 18%, transparent)", color: "var(--st-paused)", fontSize: 10.5 }}>PAUSED · after {PAUSE_REQUEST.task_name}</span>
            <span className="cap">This run needs your decision to continue</span>
          </div>
          <h3 style={{ margin: "2px 0 4px", fontSize: 16.5, fontWeight: 800, letterSpacing: "-.01em", lineHeight: 1.35 }}>{q.question}</h3>
          <p style={{ margin: 0, fontSize: 13, color: "var(--text-2)", lineHeight: 1.5 }}>{PAUSE_REQUEST.context.summary}</p>
        </div>
      </div>
      <div style={{ padding: "0 20px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
        {q.options.map((o, i) => {
          const active = choice === o.label;
          return (
            <button key={i} onClick={() => setChoice(o.label)} style={{ display: "flex", alignItems: "flex-start", gap: 11, textAlign: "left", padding: "12px 14px", borderRadius: 12, cursor: "pointer", transition: "all .14s", border: `1px solid ${active ? "color-mix(in oklab, var(--st-paused) 60%, transparent)" : "var(--border)"}`, background: active ? "color-mix(in oklab, var(--st-paused) 14%, var(--surface))" : "var(--surface)" }}>
              <span style={{ width: 20, height: 20, borderRadius: 99, border: `2px solid ${active ? "var(--st-paused)" : "var(--border-2)"}`, display: "grid", placeItems: "center", flex: "none", marginTop: 1 }}>{active && <span style={{ width: 9, height: 9, borderRadius: 99, background: "var(--st-paused)" }} />}</span>
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 2 }}>{o.label}{o.label === q.default && <span className="cap" style={{ marginLeft: 8, fontWeight: 600 }}>recommended</span>}</div>
                <div style={{ fontSize: 12.5, color: "var(--text-2)", lineHeight: 1.45 }}>{o.description}</div>
              </div>
            </button>
          );
        })}
      </div>
      <div style={{ padding: "13px 20px", borderTop: "1px solid color-mix(in oklab, var(--st-paused) 25%, transparent)", display: "flex", alignItems: "center", gap: 10, background: "color-mix(in oklab, var(--st-paused) 5%, transparent)" }}>
        <button className="btn btn-primary" onClick={() => onAnswer(choice, false)} style={{ background: "var(--st-paused)", color: "#3a2600" }}><Icons.check size={16} />Approve & continue</button>
        <div style={{ flex: 1 }} />
        <button className="btn btn-soft btn-sm" onClick={() => onAnswer("Ship as-is", true)}>Ship as-is</button>
        <button className="btn btn-ghost btn-sm" onClick={() => onAnswer("Abort", true)} style={{ color: "var(--st-failed)" }}>Abort</button>
      </div>
    </div>
  );
}

function CompletedBanner({ run, onGoBoard }) {
  return (
    <div className="fade-in" style={{ margin: "18px 0 4px", flex: "none", borderRadius: 16, border: "1px solid color-mix(in oklab, var(--st-done) 40%, transparent)", background: "color-mix(in oklab, var(--st-done) 8%, var(--surface))", padding: "18px 20px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 13, marginBottom: 15 }}>
        <span style={{ width: 40, height: 40, borderRadius: 12, background: "color-mix(in oklab, var(--st-done) 20%, transparent)", color: "var(--st-done)", display: "grid", placeItems: "center", flex: "none" }}><Icons.check size={20} /></span>
        <div>
          <h3 style={{ margin: "0 0 2px", fontSize: 17, fontWeight: 800 }}>Nice — the agent finished this run.</h3>
          <p style={{ margin: 0, fontSize: 13, color: "var(--text-2)" }}>Issue moved to <strong>In Review</strong>. Everything below is archived in history.</p>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: 16 }}>
        <SummaryStat label="Total cost" value="$13.28" accent="var(--st-done)" />
        <SummaryStat label="Tokens" value="236,900" />
        <SummaryStat label="Turns" value="153" />
        <SummaryStat label="Duration" value="43m 32s" />
      </div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <button className="btn btn-primary"><Icons.pr size={15} />Open pull request</button>
        <button className="btn btn-soft"><Icons.spark size={15} />Run next stage (dev)</button>
        <button className="btn btn-ghost" onClick={onGoBoard}>Back to board</button>
      </div>
    </div>
  );
}
function SummaryStat({ label, value, accent }) {
  return (
    <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 12, padding: "11px 13px" }}>
      <div className="mono" style={{ fontSize: 18, fontWeight: 800, color: accent || "var(--text)" }}>{value}</div>
      <div className="cap" style={{ marginTop: 1 }}>{label}</div>
    </div>
  );
}

function FailedBanner({ run, onRetry }) {
  return (
    <div className="fade-in" style={{ margin: "18px 0 4px", flex: "none", borderRadius: 16, border: "1px solid color-mix(in oklab, var(--st-failed) 40%, transparent)", background: "color-mix(in oklab, var(--st-failed) 7%, var(--surface))", padding: "18px 20px" }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 13 }}>
        <span style={{ width: 40, height: 40, borderRadius: 12, background: "color-mix(in oklab, var(--st-failed) 18%, transparent)", color: "var(--st-failed)", display: "grid", placeItems: "center", flex: "none" }}><Icons.warn size={20} /></span>
        <div style={{ flex: 1 }}>
          <h3 style={{ margin: "0 0 4px", fontSize: 16.5, fontWeight: 800 }}>This run timed out — no harm done.</h3>
          <p style={{ margin: "0 0 10px", fontSize: 13.5, color: "var(--text-2)", lineHeight: 1.5 }}>{run.error || "The sandbox exceeded its timeout."}</p>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14, padding: "8px 12px", background: "var(--surface)", borderRadius: 10, border: "1px solid var(--border)", width: "fit-content" }}>
            <Icons.retry size={14} style={{ color: "var(--st-paused)" }} />
            <span style={{ fontSize: 12.5, color: "var(--text-2)" }}>Auto-retry <strong>attempt 2 of 3</strong> · backoff <span className="mono">due in 2m 10s</span></span>
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <button className="btn btn-primary" onClick={onRetry}><Icons.retry size={15} />Retry now</button>
            <button className="btn btn-soft"><Icons.code size={15} />Open logs</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function RunRail({ run, state }) {
  const cfg = { repo: "https://github.com/asaficontact/DKMV.git", branch: "feat/codex", feature_name: "prd_multi_agent_adapter", model: run.model, max_turns: 100, timeout_minutes: 30, max_budget_usd: null, memory_limit: "8g" };
  const artifacts = state === "completed"
    ? [{ name: "analysis.json", size: "4.2 KB" }, { name: "implementation_docs/", size: "12 files" }, { name: "qa_evaluation.json", size: "1.8 KB" }, { name: "GUIDE.md", size: "8.1 KB" }]
    : state === "paused" ? [{ name: "analysis.json", size: "4.2 KB" }]
      : [{ name: "session.log", size: "live", live: true }];
  return (
    <div className="slide-in" style={{ width: 320, flex: "none", borderLeft: "1px solid var(--border)", background: "var(--surface)", overflowY: "auto", padding: "18px 18px 30px" }}>
      <RailSection title="Run config" icon={Icons.settings}>
        <div style={{ background: "var(--surface-2)", borderRadius: 11, padding: "10px 13px", display: "flex", flexDirection: "column", gap: 7 }}>
          {Object.entries(cfg).map(([k, v]) => (
            <div key={k} style={{ display: "flex", justifyContent: "space-between", gap: 10, fontSize: 11.5 }}>
              <span className="mono" style={{ color: "var(--text-3)" }}>{k}</span>
              <span className="mono" style={{ color: v === null ? "var(--text-3)" : "var(--text)", textAlign: "right", wordBreak: "break-all", fontWeight: 600 }}>{v === null ? "null" : String(v).replace("https://github.com/", "")}</span>
            </div>
          ))}
        </div>
      </RailSection>

      <RailSection title="Sandbox" icon={Icons.code}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 13px", background: "var(--surface-2)", borderRadius: 11 }}>
          <span style={{ width: 9, height: 9, borderRadius: 99, background: state === "running" ? "var(--st-done)" : state === "failed" ? "var(--st-failed)" : "var(--text-3)", flex: "none" }} />
          <div style={{ fontSize: 12 }}>
            <div className="mono" style={{ fontWeight: 600 }}>dkmv-sandbox:latest</div>
            <div className="cap">{state === "running" ? "8g · 2 vCPU · healthy" : state === "failed" ? "exited · timeout" : "8g · idle"}</div>
          </div>
        </div>
      </RailSection>

      <RailSection title="Artifacts" icon={Icons.file}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {artifacts.map((a, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 9, padding: "9px 12px", background: "var(--surface-2)", borderRadius: 10, cursor: "pointer" }}>
              <Icons.file size={14} style={{ color: "var(--st-review)", flex: "none" }} />
              <span className="mono" style={{ fontSize: 12, flex: 1, fontWeight: 600 }}>{a.name}</span>
              {a.live ? <span className="badge" style={{ background: "color-mix(in oklab, var(--st-running) 14%, transparent)", color: "var(--st-running)", fontSize: 9.5 }}>live</span> : <span className="cap mono">{a.size}</span>}
            </div>
          ))}
        </div>
      </RailSection>

      {state === "completed" && run.pr && (
        <RailSection title="Pull request" icon={Icons.pr}>
          <div style={{ padding: "12px 13px", background: "color-mix(in oklab, var(--st-review) 8%, transparent)", border: "1px solid color-mix(in oklab, var(--st-review) 25%, transparent)", borderRadius: 11 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 8 }}>
              <Icons.pr size={14} style={{ color: "var(--st-review)" }} />
              <span className="mono" style={{ fontSize: 12, fontWeight: 700 }}>#{run.pr}</span>
              <span className="badge" style={{ marginLeft: "auto", background: "color-mix(in oklab, var(--st-done) 14%, transparent)", color: "var(--st-done)", fontSize: 9.5 }}><Icons.check size={9} />checks pass</span>
            </div>
            <div style={{ fontSize: 12.5, color: "var(--text-2)", lineHeight: 1.45, marginBottom: 10 }}>fix(auth): rotate access token before expiry</div>
            <button className="btn btn-soft btn-sm" style={{ width: "100%", justifyContent: "center" }}><Icons.github size={13} />View on GitHub<Icons.ext size={12} /></button>
          </div>
        </RailSection>
      )}
    </div>
  );
}
function RailSection({ title, icon, children }) {
  const I = icon;
  return (
    <div style={{ marginBottom: 22 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 10 }}>
        <I size={14} style={{ color: "var(--text-3)" }} />
        <span style={{ fontSize: 11, fontWeight: 800, textTransform: "uppercase", letterSpacing: ".06em", color: "var(--text-2)" }}>{title}</span>
      </div>
      {children}
    </div>
  );
}

function fmtT(sec) { const m = Math.floor(sec / 60), s = sec % 60; return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`; }
function fmtClock(sec) { const m = Math.floor(sec / 60), s = Math.floor(sec % 60); return `${m}m ${String(s).padStart(2, "0")}s`; }

Object.assign(window, { LiveRun });
