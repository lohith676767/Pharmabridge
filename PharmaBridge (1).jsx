import { useState, useRef, useEffect } from "react";
import {
  Brain, Wrench, Check, X, Play, Terminal, FlaskConical,
  AlertTriangle, RefreshCw, ChevronRight, Shield, Package, ArrowRight
} from "lucide-react";

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   SYSTEM PROMPTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */

const PM_SYSTEM = `You are the Product Manager Agent in a pharmaceutical technology-transfer pipeline.

ROLE: Extract and structure critical process knowledge from pharmaceutical transfer requirements. You do NOT design the manufacturing solution — you capture what is known and flag what is NOT known.

INPUT: A plain-language client brief about transferring a pharmaceutical process to industrial manufacturing.

OUTPUT: Return ONLY valid raw JSON (no markdown fences, no prose before or after):
{
  "requirement_summary": "string",
  "parameters": [
    {
      "name": "string",
      "value": "string or null",
      "validated_range": "string or null",
      "criticality": "High" or "Medium" or "Low" or null,
      "quality_impact": "string",
      "scale_sensitivity": "High" or "Medium" or "Low" or null,
      "evidence_source": "string",
      "uncertainty": "string or null"
    }
  ],
  "dependencies": [{ "parameter": "string", "affects": "string", "note": "string" }],
  "open_questions": ["string"],
  "confidence": "Complete" or "Partial" or "Insufficient"
}

STRICT RULES:
1. Never invent values not stated or clearly inferable. If criticality, validated_range, or scale_sensitivity is unknown, set to null and add a corresponding entry to open_questions — do not guess.
2. If the brief is too vague to extract any parameters, set confidence to "Insufficient" and populate only open_questions with specific clarifying questions.
3. evidence_source is mandatory for every parameter. Use "Not stated" if unknown — never omit it.
4. Parameters validated only at pilot or lab scale must have scale_sensitivity "High" and uncertainty noting commercial scale is unvalidated.
5. Output ONLY the raw JSON object. Nothing else.`;

const SA_SYSTEM = `You are the Solution Architect Agent in a pharmaceutical technology-transfer pipeline.

ROLE: Convert the Process Knowledge Package (JSON from PM Agent) into an implementable Manufacturing Design. You see ONLY the PM Agent's JSON — never the original client brief.

CRITICAL: Run these validation checks before generating any design:
- Any parameter with null criticality, validated_range, or scale_sensitivity → BLOCK that parameter and add to block_reasons
- Conflicting values (e.g. target temperature falls outside stated safe range) → BLOCK and describe the conflict explicitly in block_reasons
- If confidence is "Insufficient" → BLOCK entirely, copy open_questions to block_reasons, set manufacturing_design to []
- Parameters with evidence only at pilot or lab scale → mark commercial_scale_status as "Unverified"

OUTPUT: Return ONLY valid raw JSON (no markdown fences, no prose):
{
  "handoff_status": "PASSED" or "BLOCKED",
  "block_reasons": ["string"],
  "manufacturing_design": [
    {
      "parameter": "string",
      "control": "string",
      "monitoring": "string",
      "validation_required": "string",
      "deviation_handling": "string",
      "traceability": "string",
      "commercial_scale_status": "Verified" or "Unverified" or "Not applicable"
    }
  ],
  "risk_flags": ["string"],
  "recommended_next_step": "string"
}

STRICT RULES:
1. Never add parameters not present in the input. Never fill fields using assumptions not in the given data.
2. Every manufacturing_design entry must trace to a specific input parameter — do not invent new ones.
3. Output ONLY the raw JSON object. Nothing else.`;

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   PYTHON-EQUIVALENT VALIDATION LAYER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */

function validateHandoff(pm) {
  if (!pm || typeof pm !== "object") return { ok: false, issues: ["Agent 1 returned invalid output"] };
  if (pm.confidence === "Insufficient") {
    const qs = pm.open_questions || [];
    return { ok: false, issues: qs.length ? qs.map(q => `Clarification needed: ${q}`) : ["Brief too vague — no parameters extractable"] };
  }
  const issues = [];
  if (!pm.parameters?.length) issues.push("No parameters extracted from brief");
  for (const p of pm.parameters || []) {
    if (!p.criticality) issues.push(`Missing criticality — "${p.name}"`);
    if (!p.validated_range) issues.push(`Missing validated range — "${p.name}"`);
    if (!p.scale_sensitivity) issues.push(`Missing scale sensitivity — "${p.name}"`);
  }
  return { ok: issues.length === 0, issues };
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   API CALL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */

async function callAgent(system, userContent) {
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: "claude-sonnet-4-6",
      max_tokens: 1000,
      system,
      messages: [{ role: "user", content: userContent }],
    }),
  });
  if (!res.ok) throw new Error(`API returned ${res.status}`);
  const data = await res.json();
  let text = data.content?.filter(b => b.type === "text").map(b => b.text).join("") || "";
  text = text.replace(/^```json\s*/i, "").replace(/^```\s*/i, "").replace(/\s*```$/i, "").trim();
  return text;
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   QUICK TEST PRESETS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */

const PRESETS = [
  {
    label: "Happy path",
    brief: "Transfer our pilot-scale tablet coating process to mass production. Coating temperature was validated at 52°C, range 51–52°C, high criticality, high scale sensitivity, evidence from pilot batch validation. Mixing speed is 150 RPM, range 140–160 RPM, medium criticality, medium scale sensitivity, evidence from R&D lab notes."
  },
  {
    label: "Vague brief",
    brief: "Transfer our tablet process to mass production."
  },
  {
    label: "Missing fields",
    brief: "Transfer our powder blending process to mass production. Blend time is 20 minutes. We think temperature matters but haven't measured it. Scale-up risk is unknown."
  }
];

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   SHARED SUB-COMPONENTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */

const BADGE_STYLES = {
  high:         { bg: "var(--bg-danger)",   color: "var(--text-danger)",   border: "var(--border-danger)" },
  medium:       { bg: "var(--bg-warning)",  color: "var(--text-warning)",  border: "var(--border-warning)" },
  low:          { bg: "var(--bg-success)",  color: "var(--text-success)",  border: "var(--border-success)" },
  verified:     { bg: "var(--bg-success)",  color: "var(--text-success)",  border: "var(--border-success)" },
  unverified:   { bg: "var(--bg-danger)",   color: "var(--text-danger)",   border: "var(--border-danger)" },
  complete:     { bg: "var(--bg-success)",  color: "var(--text-success)",  border: "var(--border-success)" },
  partial:      { bg: "var(--bg-warning)",  color: "var(--text-warning)",  border: "var(--border-warning)" },
  insufficient: { bg: "var(--bg-danger)",   color: "var(--text-danger)",   border: "var(--border-danger)" },
  accent:       { bg: "var(--bg-accent)",   color: "var(--text-accent)",   border: "var(--border-accent)" },
  neutral:      { bg: "var(--surface-2)",   color: "var(--text-secondary)",border: "var(--border)" },
};

function Badge({ text, variant = "neutral" }) {
  const s = BADGE_STYLES[variant] || BADGE_STYLES.neutral;
  return (
    <span style={{
      fontSize: 11, padding: "2px 8px", borderRadius: "var(--radius)",
      background: s.bg, color: s.color, border: `0.5px solid ${s.border}`,
      fontWeight: 500, whiteSpace: "nowrap"
    }}>{text}</span>
  );
}

function ParamCard({ p }) {
  const cv = (p.criticality || "").toLowerCase();
  const critVariant = cv === "high" ? "high" : cv === "medium" ? "medium" : cv === "low" ? "low" : "neutral";
  return (
    <div style={{ background: "var(--surface-2)", border: "0.5px solid var(--border)", borderRadius: 12, padding: "12px 14px", marginBottom: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8, gap: 8 }}>
        <span style={{ fontWeight: 500, fontSize: 13, color: "var(--text-primary)" }}>{p.name}</span>
        {p.criticality
          ? <Badge text={p.criticality} variant={critVariant} />
          : <Badge text="Criticality missing" variant="high" />}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: "4px 16px" }}>
        {[["Value", p.value], ["Range", p.validated_range], ["Scale sensitivity", p.scale_sensitivity], ["Evidence", p.evidence_source]].map(([k, v]) => (
          <div key={k} style={{ fontSize: 11 }}>
            <span style={{ color: "var(--text-muted)" }}>{k}: </span>
            <span style={{ color: v ? "var(--text-secondary)" : "var(--text-danger)", fontWeight: v ? 400 : 500 }}>
              {v || "⚠ Missing"}
            </span>
          </div>
        ))}
      </div>
      {p.uncertainty && (
        <div style={{ marginTop: 8, fontSize: 11, color: "var(--text-warning)", display: "flex", alignItems: "flex-start", gap: 4 }}>
          <AlertTriangle size={11} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>{p.uncertainty}</span>
        </div>
      )}
    </div>
  );
}

function DesignCard({ d }) {
  const sv = d.commercial_scale_status === "Verified" ? "verified" : d.commercial_scale_status === "Unverified" ? "unverified" : "neutral";
  return (
    <div style={{ background: "var(--surface-2)", border: "0.5px solid var(--border)", borderRadius: 12, padding: "12px 14px", marginBottom: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8, gap: 8 }}>
        <span style={{ fontWeight: 500, fontSize: 13, color: "var(--text-primary)" }}>{d.parameter}</span>
        <Badge text={d.commercial_scale_status || "N/A"} variant={sv} />
      </div>
      {[["Control", d.control], ["Monitoring", d.monitoring], ["Validation", d.validation_required], ["Deviation handling", d.deviation_handling]].map(([k, v]) => v && (
        <div key={k} style={{ fontSize: 11, marginBottom: 3 }}>
          <span style={{ color: "var(--text-muted)" }}>{k}: </span>
          <span style={{ color: "var(--text-secondary)" }}>{v}</span>
        </div>
      ))}
      {d.traceability && (
        <div style={{ marginTop: 8, fontSize: 11, color: "var(--text-accent)", display: "flex", alignItems: "center", gap: 4 }}>
          <ChevronRight size={11} />
          <span>Traces to: {d.traceability}</span>
        </div>
      )}
    </div>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   PROGRESS STEP BAR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */

const STEPS = [
  { label: "Brief",      icon: Terminal },
  { label: "PM Agent",   icon: Brain    },
  { label: "Validation", icon: Shield   },
  { label: "SA Agent",   icon: Wrench   },
  { label: "Blueprint",  icon: Package  },
];
const PHASE_IDX = { idle: 0, running_a1: 1, validating: 2, running_a2: 3, done: 4, error: 0 };

function ProgressBar({ stage }) {
  const cur = PHASE_IDX[stage] || 0;
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 0, marginBottom: 24, padding: "4px 0" }}>
      {STEPS.map((step, i) => {
        const done = cur > i;
        const active = cur === i;
        const Icon = step.icon;
        return (
          <div key={step.label} style={{ display: "flex", alignItems: "flex-start", flex: i < STEPS.length - 1 ? "1 1 0" : "0 0 auto" }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
              <div style={{
                width: 32, height: 32, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center",
                border: `0.5px solid ${done ? "var(--border-success)" : active ? "var(--border-accent)" : "var(--border-strong)"}`,
                background: done ? "var(--bg-success)" : active ? "var(--bg-accent)" : "var(--surface-1)",
                color: done ? "var(--text-success)" : active ? "var(--text-accent)" : "var(--text-muted)",
                transition: "all 0.4s ease",
                flexShrink: 0
              }}>
                {done ? <Check size={14} /> : <Icon size={14} />}
              </div>
              <span style={{ fontSize: 10, fontWeight: active || done ? 500 : 400, color: active ? "var(--text-accent)" : done ? "var(--text-success)" : "var(--text-muted)", whiteSpace: "nowrap" }}>
                {step.label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <div style={{ flex: 1, height: 1, marginTop: 16, background: "var(--border)", position: "relative", overflow: "hidden", marginLeft: 4, marginRight: 4 }}>
                <div style={{
                  position: "absolute", top: 0, left: 0, height: "100%",
                  width: cur > i ? "100%" : "0%",
                  background: "var(--fill-accent)",
                  transition: "width 0.6s ease"
                }} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   HANDOFF CHANNEL (centre column)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */

const VAL_CHECKS = [
  { label: "Criticality present" },
  { label: "Validated range present" },
  { label: "Scale sensitivity present" },
];

function HandoffChannel({ stage, valResult }) {
  const cur = PHASE_IDX[stage] || 0;
  const active = cur >= 2;
  const passed = valResult?.ok;

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 52, gap: 12 }}>
      <span style={{ fontSize: 11, fontWeight: 500, color: "var(--text-muted)" }}>Handoff</span>

      {/* Animated flow line */}
      <div style={{ width: "100%", display: "flex", alignItems: "center", position: "relative", height: 20 }}>
        <div style={{ width: "100%", height: 1, background: "var(--border)", position: "relative", overflow: "hidden" }}>
          <div style={{
            position: "absolute", top: 0, left: 0, height: "100%",
            width: active ? "100%" : "0%",
            background: passed === false ? "var(--border-danger)" : "var(--fill-accent)",
            transition: "width 0.8s ease"
          }} />
        </div>
        {active && (
          <div style={{
            position: "absolute", left: "50%", transform: "translateX(-50%)",
            background: "var(--surface-1)", border: `0.5px solid ${passed === false ? "var(--border-danger)" : "var(--border-accent)"}`,
            borderRadius: 4, padding: "2px 8px", fontSize: 10, fontWeight: 500,
            color: passed === false ? "var(--text-danger)" : "var(--text-accent)"
          }}>JSON</div>
        )}
      </div>

      {/* Validation checklist */}
      <div style={{ width: "100%", background: "var(--surface-1)", border: "0.5px solid var(--border)", borderRadius: 12, padding: "12px" }}>
        <div style={{ fontSize: 11, fontWeight: 500, color: "var(--text-secondary)", marginBottom: 10 }}>Checks</div>
        {VAL_CHECKS.map((vc, i) => {
          const checked = cur >= 3;
          const isBlocked = valResult && !valResult.ok;
          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: i < VAL_CHECKS.length - 1 ? 6 : 0, fontSize: 11 }}>
              <div style={{
                width: 16, height: 16, borderRadius: "50%", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center",
                border: `0.5px solid ${!active ? "var(--border)" : checked && isBlocked ? "var(--border-danger)" : checked ? "var(--border-success)" : "var(--border-accent)"}`,
                background: !active ? "var(--surface-2)" : checked && isBlocked ? "var(--bg-danger)" : checked ? "var(--bg-success)" : "var(--bg-accent)",
                transition: "all 0.3s"
              }}>
                {active && checked && isBlocked && <X size={9} color="var(--text-danger)" />}
                {active && checked && !isBlocked && <Check size={9} color="var(--text-success)" />}
              </div>
              <span style={{ color: "var(--text-muted)", fontSize: 10, lineHeight: 1.3 }}>{vc.label}</span>
            </div>
          );
        })}
      </div>

      {/* Status pill */}
      {valResult && (
        <div style={{
          width: "100%", textAlign: "center", padding: "8px", borderRadius: "var(--radius)",
          background: valResult.ok ? "var(--bg-success)" : "var(--bg-danger)",
          border: `0.5px solid ${valResult.ok ? "var(--border-success)" : "var(--border-danger)"}`,
        }}>
          <div style={{ fontSize: 12, fontWeight: 500, color: valResult.ok ? "var(--text-success)" : "var(--text-danger)" }}>
            {valResult.ok ? "✓ Passed" : "✗ Blocked"}
          </div>
        </div>
      )}

      {!valResult && (
        <div style={{ fontSize: 10, color: "var(--text-muted)", textAlign: "center", lineHeight: 1.5 }}>
          Agent 2 uses Agent 1's<br />raw JSON as sole input
        </div>
      )}
    </div>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   AGENT CARD SHELL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */

function AgentCard({ title, subtitle, iconColor, icon: Icon, statusLabel, borderColor, children }) {
  return (
    <div style={{ background: "var(--surface-1)", border: `0.5px solid ${borderColor}`, borderRadius: 12, overflow: "hidden", transition: "border-color 0.4s ease" }}>
      <div style={{ padding: "14px 16px", borderBottom: "0.5px solid var(--border)", display: "flex", alignItems: "center", gap: 8 }}>
        <Icon size={16} color={iconColor} aria-hidden="true" />
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 500, fontSize: 13, color: "var(--text-primary)" }}>{title}</div>
          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{subtitle}</div>
        </div>
        {statusLabel && (
          <span style={{ fontSize: 11, color: statusLabel.color, fontWeight: 500 }}>{statusLabel.text}</span>
        )}
      </div>
      <div style={{ padding: 16, minHeight: 300 }}>{children}</div>
    </div>
  );
}

function EmptyState({ icon: Icon, text }) {
  return (
    <div style={{ textAlign: "center", padding: "48px 16px", color: "var(--text-muted)" }}>
      <Icon size={28} style={{ margin: "0 auto 10px", opacity: 0.25 }} />
      <div style={{ fontSize: 12 }}>{text}</div>
    </div>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   MAIN APP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */

export default function PharmaBridge() {
  const [brief, setBrief] = useState("");
  const [stage, setStage] = useState("idle");
  const [a1, setA1] = useState(null);
  const [valResult, setValResult] = useState(null);
  const [a2, setA2] = useState(null);
  const [logs, setLogs] = useState([]);
  const logRef = useRef(null);

  const log = (msg, type = "sys") =>
    setLogs(p => [...p, { msg, type, t: new Date().toLocaleTimeString("en-IN", { hour12: false }) }]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs]);

  const reset = () => { setStage("idle"); setA1(null); setValResult(null); setA2(null); setLogs([]); };

  const run = async () => {
    if (!brief.trim()) return;
    setStage("running_a1"); setA1(null); setValResult(null); setA2(null); setLogs([]);
    log("Pipeline initiated — Agent 1 (Product Manager) activated", "start");
    log("Parsing client brief and extracting critical process knowledge...", "sys");

    try {
      const raw1 = await callAgent(PM_SYSTEM, `Client brief: "${brief}"`);
      let pm;
      try { pm = JSON.parse(raw1); }
      catch { setStage("error"); log("Agent 1 returned non-parseable output — check the API connection", "err"); return; }

      setA1(pm);
      log(`Agent 1 complete — confidence: ${pm.confidence}, ${pm.parameters?.length ?? 0} parameter(s) extracted`, "ok");
      if (pm.open_questions?.length) log(`Open questions raised: ${pm.open_questions.join(" | ")}`, "warn");

      setStage("validating");
      log("Python validation layer activated — checking handoff package integrity...", "sys");
      await new Promise(r => setTimeout(r, 900));

      const val = validateHandoff(pm);
      setValResult(val);

      if (!val.ok) {
        log("HANDOFF BLOCKED — " + val.issues.join(" | "), "err");
        setA2({ handoff_status: "BLOCKED", block_reasons: val.issues, manufacturing_design: [], risk_flags: [], recommended_next_step: "Resolve missing fields and resubmit to pipeline." });
        setStage("done");
        return;
      }
      log("All validation checks passed — handoff approved", "ok");

      setStage("running_a2");
      log("Agent 2 (Solution Architect) activated — input: Agent 1's raw JSON package (no original brief)", "start");
      log("Building manufacturing design controls — zero creative drift mode...", "sys");

      const raw2 = await callAgent(SA_SYSTEM, `Process Knowledge Package from PM Agent:\n${JSON.stringify(pm, null, 2)}`);
      let sa;
      try { sa = JSON.parse(raw2); }
      catch { setStage("error"); log("Agent 2 returned non-parseable output", "err"); return; }

      setA2(sa);
      log(`Agent 2 complete — handoff: ${sa.handoff_status}, ${sa.manufacturing_design?.length ?? 0} control(s) generated`, "ok");
      if (sa.risk_flags?.length) log(`Risk flags raised: ${sa.risk_flags.join(" | ")}`, "warn");
      log("Pipeline complete — full context traceability preserved across both agents", "ok");
      setStage("done");

    } catch (e) {
      setStage("error");
      log("Pipeline error: " + String(e), "err");
    }
  };

  const cur = PHASE_IDX[stage] || 0;
  const isRunning = ["running_a1", "validating", "running_a2"].includes(stage);

  const a1Border = stage === "running_a1" ? "var(--border-accent)" : cur > 1 ? "var(--border-success)" : "var(--border)";
  const a1IconColor = stage === "running_a1" ? "var(--text-accent)" : cur > 1 ? "var(--text-success)" : "var(--text-muted)";
  const a1Status = stage === "running_a1" ? { text: "Running...", color: "var(--text-accent)" } : cur > 1 ? { text: "Complete", color: "var(--text-success)" } : null;

  const a2Blocked = stage === "done" && a2?.handoff_status === "BLOCKED";
  const a2Border = stage === "running_a2" ? "var(--border-accent)" : a2Blocked ? "var(--border-danger)" : stage === "done" ? "var(--border-success)" : "var(--border)";
  const a2IconColor = a2Blocked ? "var(--text-danger)" : stage === "running_a2" ? "var(--text-accent)" : stage === "done" ? "var(--text-success)" : "var(--text-muted)";
  const a2Status = stage === "running_a2" ? { text: "Running...", color: "var(--text-accent)" } : a2Blocked ? { text: "Blocked", color: "var(--text-danger)" } : stage === "done" ? { text: "Complete", color: "var(--text-success)" } : null;

  return (
    <div style={{ padding: "0", fontFamily: "var(--font-sans)" }}>
      <h2 className="sr-only">PharmaBridge AI — two-agent pharmaceutical technology transfer pipeline</h2>

      {/* ── HEADER */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingBottom: 16, borderBottom: "0.5px solid var(--border)", marginBottom: 24 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <FlaskConical size={20} color="var(--text-accent)" aria-hidden="true" />
          <div>
            <div style={{ fontWeight: 500, fontSize: 15, color: "var(--text-primary)" }}>PharmaBridge AI</div>
            <div style={{ fontSize: 11, color: "var(--text-muted)" }}>Context-preserving pharmaceutical technology transfer</div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <Badge text="Rockathon'26 — PS2" variant="accent" />
          <Badge text="PharmaBridge · SSNCE" variant="neutral" />
        </div>
      </div>

      {/* ── PROGRESS BAR */}
      <ProgressBar stage={stage} />

      {/* ── CLIENT INPUT */}
      <div style={{ background: "var(--surface-1)", border: "0.5px solid var(--border)", borderRadius: 12, padding: "16px", marginBottom: 20 }}>
        <div style={{ fontSize: 12, fontWeight: 500, color: "var(--text-secondary)", marginBottom: 10 }}>Client requirement</div>
        <textarea
          value={brief}
          onChange={e => setBrief(e.target.value)}
          disabled={isRunning}
          placeholder='Enter the client brief — e.g. "Transfer our pilot-scale tablet coating process to mass production. Coating temperature: 52°C, range 51–52°C, high criticality, pilot batch data only."'
          style={{
            width: "100%", boxSizing: "border-box",
            background: "var(--surface-2)", border: "0.5px solid var(--border)", borderRadius: "var(--radius)",
            color: "var(--text-primary)", fontSize: 13, padding: "10px 12px",
            resize: "vertical", minHeight: 72, outline: "none",
            fontFamily: "var(--font-sans)", lineHeight: 1.6, opacity: isRunning ? 0.6 : 1
          }}
        />
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 12, flexWrap: "wrap", gap: 8 }}>
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>Quick tests:</span>
            {PRESETS.map(p => (
              <button key={p.label} onClick={() => { setBrief(p.brief); reset(); }}
                style={{ fontSize: 11, color: "var(--text-accent)", background: "var(--bg-accent)", border: "0.5px solid var(--border-accent)", borderRadius: "var(--radius)", padding: "4px 10px", cursor: "pointer" }}>
                {p.label}
              </button>
            ))}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {(stage === "done" || stage === "error") && (
              <button onClick={reset}
                style={{ fontSize: 13, color: "var(--text-secondary)", background: "var(--surface-2)", border: "0.5px solid var(--border-strong)", borderRadius: "var(--radius)", padding: "8px 14px", cursor: "pointer", display: "flex", alignItems: "center", gap: 6 }}>
                <RefreshCw size={13} /> Reset
              </button>
            )}
            <button
              onClick={!isRunning ? run : undefined}
              disabled={!brief.trim() || isRunning}
              style={{
                fontSize: 13, fontWeight: 500, padding: "8px 20px", borderRadius: "var(--radius)",
                border: "0.5px solid",
                cursor: !brief.trim() || isRunning ? "not-allowed" : "pointer",
                background: !brief.trim() || isRunning ? "var(--fill-disabled)" : "var(--fill-accent)",
                color: !brief.trim() || isRunning ? "var(--text-disabled)" : "var(--on-accent)",
                borderColor: !brief.trim() || isRunning ? "var(--border)" : "var(--fill-accent)",
                display: "flex", alignItems: "center", gap: 6
              }}>
              <Play size={13} />
              {stage === "running_a1" ? "Extracting..." : stage === "validating" ? "Validating..." : stage === "running_a2" ? "Designing..." : "Run pipeline"}
            </button>
          </div>
        </div>
      </div>

      {/* ── THREE-COLUMN PIPELINE */}
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 184px minmax(0,1fr)", gap: 16, marginBottom: 20 }}>

        {/* AGENT 1 */}
        <AgentCard
          title="Agent 1 — Product Manager"
          subtitle="Extracts and structures process knowledge"
          icon={Brain} iconColor={a1IconColor}
          borderColor={a1Border} statusLabel={a1Status}
        >
          {!a1 && stage === "idle" && <EmptyState icon={Brain} text="Awaiting client brief" />}
          {stage === "running_a1" && !a1 && <EmptyState icon={Brain} text="Extracting process parameters..." />}
          {a1 && (
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Confidence:</span>
                <Badge text={a1.confidence} variant={(a1.confidence || "").toLowerCase()} />
              </div>
              <div style={{ fontSize: 12, color: "var(--text-secondary)", background: "var(--surface-2)", padding: "8px 10px", borderRadius: "var(--radius)", marginBottom: 12, lineHeight: 1.5, border: "0.5px solid var(--border)" }}>
                {a1.requirement_summary}
              </div>
              {a1.parameters?.map((p, i) => <ParamCard key={i} p={p} />)}
              {a1.dependencies?.length > 0 && (
                <div style={{ background: "var(--surface-2)", border: "0.5px solid var(--border)", borderRadius: "var(--radius)", padding: "10px 12px", marginTop: 8 }}>
                  <div style={{ fontSize: 11, fontWeight: 500, color: "var(--text-secondary)", marginBottom: 6 }}>Dependencies</div>
                  {a1.dependencies.map((d, i) => (
                    <div key={i} style={{ fontSize: 11, color: "var(--text-secondary)", marginBottom: 3 }}>
                      <span style={{ color: "var(--text-primary)", fontWeight: 500 }}>{d.parameter}</span>
                      <span style={{ color: "var(--text-muted)" }}> → {d.affects}: </span>
                      {d.note}
                    </div>
                  ))}
                </div>
              )}
              {a1.open_questions?.length > 0 && (
                <div style={{ background: "var(--bg-warning)", border: "0.5px solid var(--border-warning)", borderRadius: "var(--radius)", padding: "10px 12px", marginTop: 8 }}>
                  <div style={{ fontSize: 11, fontWeight: 500, color: "var(--text-warning)", marginBottom: 6, display: "flex", alignItems: "center", gap: 4 }}>
                    <AlertTriangle size={12} /> Clarification required
                  </div>
                  {a1.open_questions.map((q, i) => (
                    <div key={i} style={{ fontSize: 11, color: "var(--text-warning)", marginBottom: 3 }}>• {q}</div>
                  ))}
                </div>
              )}
            </div>
          )}
        </AgentCard>

        {/* HANDOFF CHANNEL */}
        <HandoffChannel stage={stage} valResult={valResult} />

        {/* AGENT 2 */}
        <AgentCard
          title="Agent 2 — Solution Architect"
          subtitle="Builds manufacturing design from PM output only"
          icon={Wrench} iconColor={a2IconColor}
          borderColor={a2Border} statusLabel={a2Status}
        >
          {!a2 && (stage === "idle" || stage === "running_a1" || stage === "validating") &&
            <EmptyState icon={Wrench} text="Awaiting Agent 1 handoff" />}
          {stage === "running_a2" && !a2 &&
            <EmptyState icon={Wrench} text="Building manufacturing design..." />}
          {a2 && (
            <div>
              {a2.handoff_status === "BLOCKED" && (
                <div style={{ background: "var(--bg-danger)", border: "0.5px solid var(--border-danger)", borderRadius: "var(--radius)", padding: "12px 14px", marginBottom: 14 }}>
                  <div style={{ fontSize: 12, fontWeight: 500, color: "var(--text-danger)", marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
                    <X size={13} /> Handoff blocked — no design generated
                  </div>
                  {a2.block_reasons?.map((r, i) => (
                    <div key={i} style={{ fontSize: 11, color: "var(--text-danger)", marginBottom: 4 }}>• {r}</div>
                  ))}
                  {a2.recommended_next_step && (
                    <div style={{ marginTop: 10, fontSize: 11, color: "var(--text-secondary)", borderTop: "0.5px solid var(--border-danger)", paddingTop: 10 }}>
                      Next step: {a2.recommended_next_step}
                    </div>
                  )}
                </div>
              )}
              {a2.manufacturing_design?.map((d, i) => <DesignCard key={i} d={d} />)}
              {a2.risk_flags?.length > 0 && (
                <div style={{ background: "var(--bg-warning)", border: "0.5px solid var(--border-warning)", borderRadius: "var(--radius)", padding: "10px 12px", marginTop: 8 }}>
                  <div style={{ fontSize: 11, fontWeight: 500, color: "var(--text-warning)", marginBottom: 6, display: "flex", alignItems: "center", gap: 4 }}>
                    <AlertTriangle size={12} /> Risk flags
                  </div>
                  {a2.risk_flags.map((r, i) => (
                    <div key={i} style={{ fontSize: 11, color: "var(--text-warning)", marginBottom: 3 }}>⚠ {r}</div>
                  ))}
                </div>
              )}
              {a2.recommended_next_step && a2.handoff_status === "PASSED" && (
                <div style={{ marginTop: 10, fontSize: 11, color: "var(--text-secondary)", background: "var(--surface-2)", padding: "8px 10px", borderRadius: "var(--radius)", border: "0.5px solid var(--border)", display: "flex", alignItems: "flex-start", gap: 6 }}>
                  <ArrowRight size={12} style={{ flexShrink: 0, marginTop: 1, color: "var(--text-accent)" }} />
                  {a2.recommended_next_step}
                </div>
              )}
            </div>
          )}
        </AgentCard>
      </div>

      {/* ── PROCESS TRANSPARENCY LOG */}
      <div style={{ background: "var(--surface-1)", border: "0.5px solid var(--border)", borderRadius: 12, overflow: "hidden" }}>
        <div style={{ padding: "10px 16px", borderBottom: "0.5px solid var(--border)", display: "flex", alignItems: "center", gap: 8 }}>
          <Terminal size={13} color="var(--text-muted)" aria-hidden="true" />
          <span style={{ fontSize: 11, fontWeight: 500, color: "var(--text-secondary)" }}>Process transparency log</span>
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 7, height: 7, borderRadius: "50%", background: isRunning ? "var(--fill-success)" : "var(--fill-secondary)", transition: "background 0.3s" }} />
            <span style={{ fontSize: 10, color: "var(--text-muted)" }}>{isRunning ? "Live" : "Idle"}</span>
          </div>
        </div>
        <div ref={logRef} style={{ padding: "12px 16px", maxHeight: 150, overflowY: "auto", fontFamily: "var(--font-mono)", fontSize: 11 }}>
          {logs.length === 0 && <div style={{ color: "var(--text-muted)" }}>$ Awaiting pipeline start...</div>}
          {logs.map((l, i) => (
            <div key={i} style={{ marginBottom: 4, lineHeight: 1.5, color: l.type === "err" ? "var(--text-danger)" : l.type === "ok" ? "var(--text-success)" : l.type === "warn" ? "var(--text-warning)" : l.type === "start" ? "var(--text-accent)" : "var(--text-secondary)" }}>
              <span style={{ color: "var(--text-muted)" }}>[{l.t}]&nbsp;</span>{l.msg}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
