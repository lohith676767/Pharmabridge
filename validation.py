"""Python validation layer that gates the handoff from Agent 1 to Agent 2.

Risk-tiered per ICH Q9 (quality risk management): High-criticality
parameters — the ones with real patient-safety/quality impact — must be
fully specified (range + scale sensitivity) before handoff. Medium/Low
criticality gaps are recorded as warnings but don't block, since they
carry materially less risk if a value turns out to be unverified. A
parameter's criticality itself is always mandatory — risk can't be
tiered if it's unknown.
"""

from schemas import PMOutput, ValidationResult


def validate_handoff(pm: PMOutput) -> ValidationResult:
    if pm is None:
        return ValidationResult(ok=False, issues=["Agent 1 returned invalid output"])

    if pm.confidence == "Insufficient":
        if pm.open_questions:
            issues = [f"Clarification needed: {q}" for q in pm.open_questions]
        else:
            issues = ["Brief too vague — no parameters extractable"]
        return ValidationResult(ok=False, issues=issues)

    issues = []
    warnings = []
    if not pm.parameters:
        issues.append("No parameters extracted from brief")

    for p in pm.parameters:
        if not p.criticality:
            issues.append(f'Missing criticality — "{p.name}" (risk cannot be assessed)')
            continue

        if p.criticality == "High":
            if not p.validated_range:
                issues.append(f'Missing validated range — "{p.name}" (High criticality)')
            if not p.scale_sensitivity:
                issues.append(f'Missing scale sensitivity — "{p.name}" (High criticality)')
        else:
            if not p.validated_range:
                warnings.append(f'Missing validated range — "{p.name}" ({p.criticality} criticality, non-blocking)')
            if not p.scale_sensitivity:
                warnings.append(f'Missing scale sensitivity — "{p.name}" ({p.criticality} criticality, non-blocking)')

    return ValidationResult(ok=len(issues) == 0, issues=issues + warnings)
