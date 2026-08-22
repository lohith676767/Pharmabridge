"""FastAPI backend for PharmaBridge AI.

Exposes the two-agent tech-transfer pipeline as a REST API, persists every
run and its audit trail to SQLite, and serves the static frontend.
"""

import os
import sys
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))  # so `import agents/schemas/validation` at repo root resolves

from agents import (  # noqa: E402
    OPEN_SOURCE_MODELS,
    AgentError,
    extract_lab_notes_text,
    extract_pdf_text,
    fetch_available_models,
    run_pm_agent,
    run_sa_agent,
)
from schemas import AgentConfig, SAOutput  # noqa: E402
from validation import validate_handoff  # noqa: E402

from backend import db  # noqa: E402

FRONTEND_DIR = ROOT_DIR / "frontend"

app = FastAPI(title="PharmaBridge AI API", version="1.0.0")

# The frontend is served by this same app, so cross-origin access is not
# needed by default. Set ALLOWED_ORIGINS (comma-separated) to open it up.
_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.on_event("startup")
def on_startup():
    db.init_db()


# ──────────────────────────────────────────────
# Pipeline
# ──────────────────────────────────────────────

@app.get("/api/models")
def get_models(base_url: str = "https://openrouter.ai/api/v1/chat/completions", api_key: str = ""):
    """Live model catalog for the given endpoint. Falls back to the static
    OPEN_SOURCE_MODELS list if the endpoint can't be reached (e.g. no key
    entered yet, or an offline/custom endpoint)."""
    try:
        return {"models": fetch_available_models(base_url, api_key), "live": True}
    except AgentError:
        return {"models": OPEN_SOURCE_MODELS, "live": False}


@app.post("/api/pipeline/run")
async def run_pipeline(
    client_text: str = Form(""),
    a1_key: str = Form(...),
    a1_model: str = Form(...),
    a1_base_url: str = Form("https://openrouter.ai/api/v1/chat/completions"),
    a2_key: str = Form(...),
    a2_model: str = Form(...),
    a2_base_url: str = Form("https://openrouter.ai/api/v1/chat/completions"),
    pilot_report: Optional[UploadFile] = File(None),
    lab_notes: Optional[UploadFile] = File(None),
):
    pilot_report_text = ""
    lab_notes_text = ""
    pilot_report_filename = pilot_report.filename if pilot_report else None
    lab_notes_filename = lab_notes.filename if lab_notes else None

    run_id = db.create_run(client_text, pilot_report_filename, lab_notes_filename)
    db.add_audit_entry(run_id, "System", "Pipeline run started", f"client_text_len={len(client_text)}", "INFO")

    try:
        if pilot_report is not None:
            pilot_report_text = extract_pdf_text(await pilot_report.read())
            db.add_audit_entry(run_id, "System", "Pilot report parsed", pilot_report_filename, "INFO")

        if lab_notes is not None:
            lab_notes_text = extract_lab_notes_text(await lab_notes.read(), lab_notes_filename)
            db.add_audit_entry(run_id, "System", "Lab notes parsed", lab_notes_filename, "INFO")

        a1_config = AgentConfig(api_key=a1_key, model=a1_model, base_url=a1_base_url)
        a2_config = AgentConfig(api_key=a2_key, model=a2_model, base_url=a2_base_url)

        db.add_audit_entry(run_id, "PM Agent", "Extraction started", a1_model, "INFO")
        pm = run_pm_agent(a1_config, client_text, pilot_report_text, lab_notes_text)
        db.update_run(run_id, pm=pm.model_dump())
        db.add_audit_entry(
            run_id, "PM Agent", "Extraction complete",
            f"confidence={pm.confidence}, parameters={len(pm.parameters)}", "PASS",
        )
        if pm.open_questions:
            db.add_audit_entry(run_id, "PM Agent", "Open questions raised", " | ".join(pm.open_questions), "WARN")

        val = validate_handoff(pm)
        db.update_run(run_id, validation=val.model_dump())

        if not val.ok:
            db.add_audit_entry(run_id, "Validation Layer", "Handoff BLOCKED", " | ".join(val.issues), "BLOCK")
            sa = SAOutput(
                handoff_status="BLOCKED",
                block_reasons=val.issues,
                manufacturing_design=[],
                risk_flags=[],
                recommended_next_step="Resolve missing fields and resubmit to pipeline.",
            )
            db.update_run(run_id, sa=sa.model_dump(), status="BLOCKED")
            db.add_audit_entry(run_id, "System", "Pipeline complete", "Blocked at validation layer", "BLOCK")
            return {"run_id": run_id, "pm": pm.model_dump(), "validation": val.model_dump(), "sa": sa.model_dump()}

        db.add_audit_entry(run_id, "Validation Layer", "Handoff PASSED", "All required fields present", "PASS")

        db.add_audit_entry(run_id, "SA Agent", "Design started", f"input=PM Agent JSON only, model={a2_model}", "INFO")
        sa = run_sa_agent(a2_config, pm)
        db.update_run(run_id, sa=sa.model_dump(), status="PASSED" if sa.handoff_status == "PASSED" else "BLOCKED")
        db.add_audit_entry(
            run_id, "SA Agent", "Design complete",
            f"handoff={sa.handoff_status}, controls={len(sa.manufacturing_design)}", "PASS",
        )
        if sa.risk_flags:
            db.add_audit_entry(run_id, "SA Agent", "Risk flags raised", " | ".join(sa.risk_flags), "WARN")

        db.add_audit_entry(run_id, "System", "Pipeline complete", "Full traceability preserved", "PASS")

        return {"run_id": run_id, "pm": pm.model_dump(), "validation": val.model_dump(), "sa": sa.model_dump()}

    except AgentError as e:
        db.update_run(run_id, status="ERROR")
        db.add_audit_entry(run_id, "System", "Pipeline error", str(e), "ERROR")
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        db.update_run(run_id, status="ERROR")
        db.add_audit_entry(run_id, "System", "Unexpected error", str(e), "ERROR")
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────
# History / audit
# ──────────────────────────────────────────────

@app.get("/api/runs")
def get_runs(limit: int = 50):
    return {"runs": db.list_runs(limit=limit)}


@app.get("/api/runs/{run_id}")
def get_run(run_id: int):
    run = db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    run["audit"] = db.list_audit(run_id=run_id)
    return run


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: int):
    if not db.delete_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return {"deleted": run_id}


@app.get("/api/audit")
def get_audit(run_id: Optional[int] = None, status: Optional[str] = None, agent: Optional[str] = None, limit: int = 500):
    return {"entries": db.list_audit(run_id=run_id, status=status, agent=agent, limit=limit)}


@app.get("/api/dashboard")
def get_dashboard():
    return db.dashboard_stats()


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ──────────────────────────────────────────────
# Static frontend
# ──────────────────────────────────────────────

if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")

    @app.get("/")
    def serve_index():
        return FileResponse(FRONTEND_DIR / "index.html")
