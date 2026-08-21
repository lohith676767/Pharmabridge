"""Python validation layer that gates the handoff from Agent 1 to Agent 2.

Mirrors the strict, no-guessing validation performed in the original
JS prototype (validateHandoff) so the pipeline behaves identically
regardless of front end.
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
    if not pm.parameters:
        issues.append("No parameters extracted from brief")

    for p in pm.parameters:
        if not p.criticality:
            issues.append(f'Missing criticality — "{p.name}"')
        if not p.validated_range:
            issues.append(f'Missing validated range — "{p.name}"')
        if not p.scale_sensitivity:
            issues.append(f'Missing scale sensitivity — "{p.name}"')

    return ValidationResult(ok=len(issues) == 0, issues=issues)
