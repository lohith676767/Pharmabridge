"""Agent 1 (Product Manager) and Agent 2 (Solution Architect) for the
PharmaBridge tech-transfer pipeline.

Both agents call OpenAI-compatible chat-completion endpoints, so they can be
pointed at any open-source-model provider (OpenRouter, Groq, Together.ai,
a local Ollama/vLLM server, etc). Each agent has its OWN API key + model,
set independently in the UI — Agent 2 never sees the original client input,
only Agent 1's structured JSON, to prevent context drift.
"""

import json
import io
import requests
from typing import Optional

from schemas import AgentConfig, PMOutput, SAOutput

# ──────────────────────────────────────────────
# Open-source model choices (OpenRouter model ids)
# ──────────────────────────────────────────────
OPEN_SOURCE_MODELS = [
    "meta-llama/llama-3.1-70b-instruct",
    "meta-llama/llama-3.1-8b-instruct",
    "mistralai/mixtral-8x7b-instruct",
    "mistralai/mistral-7b-instruct",
    "qwen/qwen-2.5-72b-instruct",
    "deepseek/deepseek-chat",
]

PM_SYSTEM = """You are the Product Manager Agent in a pharmaceutical technology-transfer pipeline.

ROLE: Extract and structure critical process knowledge from pharmaceutical transfer requirements. You do NOT design the manufacturing solution — you capture what is known and flag what is NOT known.

INPUT: A plain-language client brief (optionally supplemented by pilot report text and lab notes text extracted from uploaded files) about transferring a pharmaceutical process to industrial manufacturing.

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
2. If the combined input is too vague to extract any parameters, set confidence to "Insufficient" and populate only open_questions with specific clarifying questions.
3. evidence_source is mandatory for every parameter. Use "Not stated" if unknown — never omit it. When a value comes from the pilot report or lab notes, say so explicitly (e.g. "Pilot report" or "Lab notes").
4. Parameters validated only at pilot or lab scale must have scale_sensitivity "High" and uncertainty noting commercial scale is unvalidated.
5. Output ONLY the raw JSON object. Nothing else."""

SA_SYSTEM = """You are the Solution Architect Agent in a pharmaceutical technology-transfer pipeline.

ROLE: Convert the Process Knowledge Package (JSON from PM Agent) into an implementable Manufacturing Design. You see ONLY the PM Agent's JSON — never the original client brief, pilot report, or lab notes.

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
3. Output ONLY the raw JSON object. Nothing else."""


class AgentError(Exception):
    pass


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    return text.strip()


def call_agent(config: AgentConfig, system: str, user_content: str) -> str:
    """Call an OpenAI-compatible chat completion endpoint with the given
    agent's own API key and model (independent per-agent configuration)."""
    if not config.api_key:
        raise AgentError("Missing API key for this agent")

    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0,
        "max_tokens": 2000,
    }
    resp = requests.post(config.base_url, headers=headers, json=payload, timeout=90)
    if not resp.ok:
        raise AgentError(f"API returned {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise AgentError(f"Unexpected API response shape: {e}")

    return _strip_json_fences(text)


# ──────────────────────────────────────────────
# Input extraction helpers (pilot report PDF, lab notes image)
# ──────────────────────────────────────────────

def extract_pdf_text(file_bytes: bytes) -> str:
    """Extract plain text from a pilot report PDF."""
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise AgentError("pypdf is required to read PDF pilot reports — pip install pypdf") from e

    reader = PdfReader(io.BytesIO(file_bytes))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages).strip()


def extract_image_text(file_bytes: bytes) -> str:
    """Best-effort OCR of a lab notes image (jpg/png/jpeg). Returns an empty
    string (with a note) if OCR is unavailable rather than failing the run."""
    try:
        from PIL import Image
        import pytesseract
    except ImportError:
        return "[Lab notes image attached — OCR unavailable, install pillow + pytesseract to extract text]"

    try:
        image = Image.open(io.BytesIO(file_bytes))
        text = pytesseract.image_to_string(image)
        return text.strip() or "[Lab notes image attached — OCR found no readable text]"
    except Exception as e:
        return f"[Lab notes image attached — OCR failed: {e}]"


def extract_lab_notes_text(file_bytes: bytes, filename: str) -> str:
    """Extract text from a lab notes upload, dispatching on file type.
    Supports images (jpg/jpeg/png, via OCR), PDFs (native lab notes or an
    exported ELN record), and plain-text/CSV exports from an ELN."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "pdf":
        text = extract_pdf_text(file_bytes)
        return text or "[Lab notes PDF attached — no extractable text found]"

    if ext in ("jpg", "jpeg", "png"):
        return extract_image_text(file_bytes)

    if ext in ("txt", "csv"):
        try:
            return file_bytes.decode("utf-8", errors="ignore").strip()
        except Exception as e:
            return f"[Lab notes file attached — decode failed: {e}]"

    raise AgentError(f"Unsupported lab notes file type: .{ext}")


def build_agent1_input(client_text: str, pilot_report_text: str = "", lab_notes_text: str = "") -> str:
    """Combine the three Agent 1 input sources into one prompt payload."""
    sections = [f"Client brief: \"{client_text.strip()}\""] if client_text.strip() else []
    if pilot_report_text.strip():
        sections.append(f"Pilot report (extracted text):\n{pilot_report_text.strip()}")
    if lab_notes_text.strip():
        sections.append(f"Lab notes (extracted text):\n{lab_notes_text.strip()}")
    if not sections:
        raise AgentError("At least one input (client text, pilot report, or lab notes) is required")
    return "\n\n".join(sections)


# ──────────────────────────────────────────────
# Agent runners
# ──────────────────────────────────────────────

def run_pm_agent(config: AgentConfig, client_text: str, pilot_report_text: str = "", lab_notes_text: str = "") -> PMOutput:
    user_content = build_agent1_input(client_text, pilot_report_text, lab_notes_text)
    raw = call_agent(config, PM_SYSTEM, user_content)
    try:
        return PMOutput.model_validate(json.loads(raw))
    except (json.JSONDecodeError, Exception) as e:
        raise AgentError(f"Agent 1 returned non-parseable output: {e}\nRaw: {raw[:500]}")


def run_sa_agent(config: AgentConfig, pm: PMOutput) -> SAOutput:
    user_content = f"Process Knowledge Package from PM Agent:\n{pm.model_dump_json(indent=2)}"
    raw = call_agent(config, SA_SYSTEM, user_content)
    try:
        return SAOutput.model_validate(json.loads(raw))
    except (json.JSONDecodeError, Exception) as e:
        raise AgentError(f"Agent 2 returned non-parseable output: {e}\nRaw: {raw[:500]}")
