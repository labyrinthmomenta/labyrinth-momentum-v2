from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    expected: float | None
    actual: float | None
    difference: float | None
    message: str


def compare(expected: float | None, actual: float | None, tolerance: float = 1e-9) -> ValidationResult:
    if expected is None and actual is None:
        return ValidationResult(True, expected, actual, 0.0, "PASS")
    if expected is None or actual is None:
        return ValidationResult(False, expected, actual, None, "One side is NULL")
    diff = abs(expected - actual)
    return ValidationResult(diff <= tolerance, expected, actual, diff, "PASS" if diff <= tolerance else "FAIL")
