"""Pydantic data models shared between the PM (Agent 1) and SA (Agent 2) agents."""

from typing import List, Optional
from pydantic import BaseModel, Field


class Parameter(BaseModel):
    name: str
    value: Optional[str] = None
    validated_range: Optional[str] = None
    criticality: Optional[str] = None  # "High" | "Medium" | "Low" | None
    quality_impact: Optional[str] = None
    scale_sensitivity: Optional[str] = None  # "High" | "Medium" | "Low" | None
    evidence_source: Optional[str] = None
    uncertainty: Optional[str] = None


class Dependency(BaseModel):
    parameter: str
    affects: str
    note: Optional[str] = None


class PMOutput(BaseModel):
    """Output of Agent 1 — Product Manager."""
    requirement_summary: str
    parameters: List[Parameter] = Field(default_factory=list)
    dependencies: List[Dependency] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    confidence: str = "Partial"  # "Complete" | "Partial" | "Insufficient" — defaults if the model omits it


class ManufacturingControl(BaseModel):
    parameter: str
    control: Optional[str] = None
    monitoring: Optional[str] = None
    validation_required: Optional[str] = None
    deviation_handling: Optional[str] = None
    traceability: Optional[str] = None
    commercial_scale_status: Optional[str] = None  # "Verified" | "Unverified" | "Not applicable"


class SAOutput(BaseModel):
    """Output of Agent 2 — Solution Architect."""
    handoff_status: str  # "PASSED" | "BLOCKED"
    block_reasons: List[str] = Field(default_factory=list)
    manufacturing_design: List[ManufacturingControl] = Field(default_factory=list)
    risk_flags: List[str] = Field(default_factory=list)
    recommended_next_step: Optional[str] = None


class ValidationResult(BaseModel):
    ok: bool
    issues: List[str] = Field(default_factory=list)


class AgentConfig(BaseModel):
    """Per-agent configuration: each agent can use its own open-source model provider/key."""
    api_key: str
    model: str
    base_url: str = "https://openrouter.ai/api/v1/chat/completions"
