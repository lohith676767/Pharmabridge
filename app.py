"""PharmaBridge AI — Streamlit front end.

Reproduces the two-agent pipeline workflow (Agent 1 → Python validation
layer → Agent 2) from the original React/Vue prototypes, wired to real
open-source LLM APIs instead of mock data.
"""

import streamlit as st

from agents import (
    OPEN_SOURCE_MODELS,
    AgentError,
    extract_image_text,
    extract_pdf_text,
    run_pm_agent,
    run_sa_agent,
)
from schemas import AgentConfig
from validation import validate_handoff

st.set_page_config(page_title="PharmaBridge AI", page_icon="🧪", layout="wide")

if "logs" not in st.session_state:
    st.session_state.logs = []
if "pm" not in st.session_state:
    st.session_state.pm = None
if "val" not in st.session_state:
    st.session_state.val = None
if "sa" not in st.session_state:
    st.session_state.sa = None


def log(msg: str, kind: str = "sys"):
    st.session_state.logs.append((kind, msg))


def reset():
    st.session_state.logs = []
    st.session_state.pm = None
    st.session_state.val = None
    st.session_state.sa = None


# ── Sidebar: per-agent API configuration (both open-source) ────────────
with st.sidebar:
    st.header("🔑 Agent API configuration")
    st.caption("Each agent uses its own key/model — both point at open-source models "
               "(e.g. via OpenRouter, Groq, Together.ai, or a local Ollama/vLLM endpoint).")

    st.subheader("Agent 1 — Product Manager")
    a1_key = st.text_input("Agent 1 API key", type="password", key="a1_key")
    a1_model = st.selectbox("Agent 1 model", OPEN_SOURCE_MODELS, key="a1_model")
    a1_base_url = st.text_input(
        "Agent 1 endpoint (OpenAI-compatible)",
        value="https://openrouter.ai/api/v1/chat/completions",
        key="a1_base_url",
    )

    st.subheader("Agent 2 — Solution Architect")
    a2_key = st.text_input("Agent 2 API key", type="password", key="a2_key")
    a2_model = st.selectbox("Agent 2 model", OPEN_SOURCE_MODELS, index=1, key="a2_model")
    a2_base_url = st.text_input(
        "Agent 2 endpoint (OpenAI-compatible)",
        value="https://openrouter.ai/api/v1/chat/completions",
        key="a2_base_url",
    )

st.title("🧪 PharmaBridge AI")
st.caption("Context-preserving pharmaceutical technology transfer — Agent 1 extracts, "
           "a Python validation layer gates the handoff, Agent 2 designs.")

# ── Agent 1 inputs ───────────────────────────────────────────────────
st.subheader("Agent 1 inputs")
col1, col2, col3 = st.columns(3)

with col1:
    pilot_report_file = st.file_uploader("1. Pilot report (.pdf)", type=["pdf"])
with col2:
    lab_notes_file = st.file_uploader("2. Lab notes (.jpg / .jpeg / .png)", type=["jpg", "jpeg", "png"])
with col3:
    st.markdown("3. Vague client text")
    client_text = st.text_area(
        "Client requirement",
        placeholder='e.g. "Transfer our pilot-scale tablet coating process to mass production..."',
        height=150,
        label_visibility="collapsed",
    )

run_col, reset_col = st.columns([1, 1])
run_clicked = run_col.button("▶ Run pipeline", type="primary")
if reset_col.button("↺ Reset"):
    reset()
    st.rerun()

if run_clicked:
    reset()

    if not a1_key or not a2_key:
        st.error("Both Agent 1 and Agent 2 API keys are required.")
        st.stop()

    pilot_report_text = ""
    lab_notes_text = ""

    if pilot_report_file is not None:
        with st.spinner("Extracting pilot report PDF..."):
            try:
                pilot_report_text = extract_pdf_text(pilot_report_file.read())
                log(f"Pilot report parsed — {len(pilot_report_text)} chars extracted", "ok")
            except AgentError as e:
                log(f"Pilot report extraction failed: {e}", "err")

    if lab_notes_file is not None:
        with st.spinner("Running OCR on lab notes image..."):
            lab_notes_text = extract_image_text(lab_notes_file.read())
            log("Lab notes image processed", "ok")

    a1_config = AgentConfig(api_key=a1_key, model=a1_model, base_url=a1_base_url)
    a2_config = AgentConfig(api_key=a2_key, model=a2_model, base_url=a2_base_url)

    log("Pipeline initiated — Agent 1 (Product Manager) activated", "start")
    try:
        with st.spinner("Agent 1 extracting process knowledge..."):
            pm = run_pm_agent(a1_config, client_text, pilot_report_text, lab_notes_text)
        st.session_state.pm = pm
        log(f"Agent 1 complete — confidence: {pm.confidence}, {len(pm.parameters)} parameter(s) extracted", "ok")
        if pm.open_questions:
            log("Open questions raised: " + " | ".join(pm.open_questions), "warn")

        with st.spinner("Running Python validation layer..."):
            val = validate_handoff(pm)
        st.session_state.val = val

        if not val.ok:
            log("HANDOFF BLOCKED — " + " | ".join(val.issues), "err")
            from schemas import SAOutput
            st.session_state.sa = SAOutput(
                handoff_status="BLOCKED",
                block_reasons=val.issues,
                manufacturing_design=[],
                risk_flags=[],
                recommended_next_step="Resolve missing fields and resubmit to pipeline.",
            )
        else:
            log("All validation checks passed — handoff approved", "ok")
            log("Agent 2 (Solution Architect) activated — input: Agent 1's JSON only", "start")
            with st.spinner("Agent 2 building manufacturing design..."):
                sa = run_sa_agent(a2_config, pm)
            st.session_state.sa = sa
            log(f"Agent 2 complete — handoff: {sa.handoff_status}, {len(sa.manufacturing_design)} control(s) generated", "ok")
            if sa.risk_flags:
                log("Risk flags raised: " + " | ".join(sa.risk_flags), "warn")
            log("Pipeline complete — full context traceability preserved across both agents", "ok")

    except AgentError as e:
        log(f"Pipeline error: {e}", "err")
        st.error(str(e))

# ── Pipeline progress ────────────────────────────────────────────────
st.divider()
steps = ["Brief", "PM Agent", "Validation", "SA Agent", "Blueprint"]
if st.session_state.sa is not None:
    cur = 5
elif st.session_state.val is not None:
    cur = 3
elif st.session_state.pm is not None:
    cur = 2
else:
    cur = 0
st.progress(cur / len(steps), text=" → ".join(f"**{s}**" if i < cur else s for i, s in enumerate(steps, 1)))

# ── Two-column agent output ──────────────────────────────────────────
out1, out2 = st.columns(2)

with out1:
    st.markdown("### Agent 1 — Product Manager")
    pm = st.session_state.pm
    if pm is None:
        st.info("Awaiting pipeline run")
    else:
        st.markdown(f"**Confidence:** {pm.confidence}")
        st.write(pm.requirement_summary)
        for p in pm.parameters:
            with st.expander(p.name):
                st.write(f"Value: {p.value or '⚠ Missing'}")
                st.write(f"Range: {p.validated_range or '⚠ Missing'}")
                st.write(f"Criticality: {p.criticality or '⚠ Missing'}")
                st.write(f"Scale sensitivity: {p.scale_sensitivity or '⚠ Missing'}")
                st.write(f"Evidence: {p.evidence_source or '⚠ Missing'}")
                if p.uncertainty:
                    st.warning(p.uncertainty)
        if pm.dependencies:
            st.markdown("**Dependencies**")
            for d in pm.dependencies:
                st.write(f"{d.parameter} → {d.affects}: {d.note}")
        if pm.open_questions:
            st.warning("Clarification required:\n" + "\n".join(f"- {q}" for q in pm.open_questions))

with out2:
    st.markdown("### Agent 2 — Solution Architect")
    sa = st.session_state.sa
    if sa is None:
        st.info("Awaiting Agent 1 handoff")
    else:
        if sa.handoff_status == "BLOCKED":
            st.error("Handoff blocked — no design generated\n\n" + "\n".join(f"- {r}" for r in sa.block_reasons))
        for d in sa.manufacturing_design:
            with st.expander(f"{d.parameter} ({d.commercial_scale_status or 'N/A'})"):
                st.write(f"Control: {d.control}")
                st.write(f"Monitoring: {d.monitoring}")
                st.write(f"Validation required: {d.validation_required}")
                st.write(f"Deviation handling: {d.deviation_handling}")
                st.write(f"Traces to: {d.traceability}")
        if sa.risk_flags:
            st.warning("Risk flags:\n" + "\n".join(f"- {r}" for r in sa.risk_flags))
        if sa.recommended_next_step:
            st.info(f"Next step: {sa.recommended_next_step}")

# ── Process transparency log ─────────────────────────────────────────
st.divider()
st.markdown("### Process transparency log")
if not st.session_state.logs:
    st.caption("$ Awaiting pipeline start...")
else:
    log_text = "\n".join(f"[{kind.upper()}] {msg}" for kind, msg in st.session_state.logs)
    st.code(log_text, language="text")
