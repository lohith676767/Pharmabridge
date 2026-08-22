"""SQLite persistence layer for pipeline runs and the audit trail.

Kept intentionally small (stdlib sqlite3, no ORM) since the data model is
just two tables: one row per pipeline run, and an append-only audit log
of every step taken during that run.
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

# Overridable so a deployment can point this at a mounted persistent disk.
# On hosts with an ephemeral filesystem (e.g. free tiers) the default path
# is wiped on every redeploy/restart — set PHARMABRIDGE_DB to keep history.
DB_PATH = Path(os.environ.get("PHARMABRIDGE_DB") or (Path(__file__).parent / "pharmabridge.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    client_text TEXT,
    pilot_report_filename TEXT,
    lab_notes_filename TEXT,
    pm_json TEXT,
    validation_json TEXT,
    sa_json TEXT,
    status TEXT NOT NULL  -- RUNNING | PASSED | BLOCKED | ERROR
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    timestamp TEXT NOT NULL,
    agent TEXT NOT NULL,       -- PM Agent | SA Agent | Validation Layer | System
    event TEXT NOT NULL,
    detail TEXT,
    status TEXT NOT NULL       -- INFO | PASS | WARN | BLOCK | ERROR
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def create_run(client_text: str, pilot_report_filename: Optional[str], lab_notes_filename: Optional[str]) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO runs (created_at, client_text, pilot_report_filename, lab_notes_filename, status) "
            "VALUES (?, ?, ?, ?, 'RUNNING')",
            (_now(), client_text, pilot_report_filename, lab_notes_filename),
        )
        return cur.lastrowid


def update_run(run_id: int, *, pm=None, validation=None, sa=None, status: Optional[str] = None) -> None:
    fields, values = [], []
    if pm is not None:
        fields.append("pm_json = ?")
        values.append(json.dumps(pm))
    if validation is not None:
        fields.append("validation_json = ?")
        values.append(json.dumps(validation))
    if sa is not None:
        fields.append("sa_json = ?")
        values.append(json.dumps(sa))
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if not fields:
        return
    values.append(run_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE runs SET {', '.join(fields)} WHERE id = ?", values)


def add_audit_entry(run_id: int, agent: str, event: str, detail: str, status: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO audit_log (run_id, timestamp, agent, event, detail, status) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, _now(), agent, event, detail, status),
        )


def list_runs(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, created_at, client_text, status, pm_json FROM runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    result = []
    for r in rows:
        pm = json.loads(r["pm_json"]) if r["pm_json"] else None
        result.append({
            "id": r["id"],
            "created_at": r["created_at"],
            "client_text": r["client_text"],
            "status": r["status"],
            "confidence": pm.get("confidence") if pm else None,
            "parameter_count": len(pm.get("parameters", [])) if pm else 0,
        })
    return result


def get_run(run_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "client_text": row["client_text"],
        "pilot_report_filename": row["pilot_report_filename"],
        "lab_notes_filename": row["lab_notes_filename"],
        "status": row["status"],
        "pm": json.loads(row["pm_json"]) if row["pm_json"] else None,
        "validation": json.loads(row["validation_json"]) if row["validation_json"] else None,
        "sa": json.loads(row["sa_json"]) if row["sa_json"] else None,
    }


def list_audit(run_id: Optional[int] = None, status: Optional[str] = None, agent: Optional[str] = None, limit: int = 500) -> list[dict]:
    query = "SELECT * FROM audit_log WHERE 1=1"
    params: list = []
    if run_id is not None:
        query += " AND run_id = ?"
        params.append(run_id)
    if status:
        query += " AND status = ?"
        params.append(status)
    if agent:
        query += " AND agent = ?"
        params.append(agent)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def dashboard_stats() -> dict:
    with get_conn() as conn:
        total_runs = conn.execute("SELECT COUNT(*) c FROM runs").fetchone()["c"]
        passed = conn.execute("SELECT COUNT(*) c FROM runs WHERE status = 'PASSED'").fetchone()["c"]
        blocked = conn.execute("SELECT COUNT(*) c FROM runs WHERE status = 'BLOCKED'").fetchone()["c"]
        errored = conn.execute("SELECT COUNT(*) c FROM runs WHERE status = 'ERROR'").fetchone()["c"]
        audit_total = conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
    return {
        "total_runs": total_runs,
        "passed": passed,
        "blocked": blocked,
        "errored": errored,
        "audit_entries": audit_total,
        "pass_rate": round(100 * passed / total_runs, 1) if total_runs else 0.0,
    }
