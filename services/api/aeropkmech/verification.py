from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from .domain import Design
from .engineering import validate


class VerificationState(StrEnum):
    PASSED = "PASSED"
    WARNING = "WARNING"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    UNTESTED = "UNTESTED"
    UNOBSERVABLE = "UNOBSERVABLE"
    EXECUTION_ERROR = "EXECUTION_ERROR"


class VerificationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: VerificationState
    summary: str
    evidence: list[str] = Field(default_factory=list)


def summarize(design: Design) -> dict[str, VerificationItem]:
    issues = validate(design)
    validation = VerificationItem(
        state=VerificationState.FAILED if issues else VerificationState.PASSED,
        summary="Design schema and implemented ratio/finite-value checks.",
        evidence=issues or ["Current project satisfies the implemented checks."],
    )
    overall_state = VerificationState.FAILED if issues else VerificationState.PARTIAL
    return {
        "overall": VerificationItem(
            state=overall_state,
            summary=(
                "The design fails one or more implemented input-consistency checks; this does not calculate mechanical failure."
                if issues
                else "Scope: implemented schema and ratio consistency checks, calculated ideal kinematics, and sampled involute CAD status. Mechanical performance is not verified; this is not a safety finding."
            ),
            evidence=(
                issues
                if issues
                else ["Tooth strength and contact are not established; thermal analysis is untested; service conditions are unobservable."]
            ),
        ),
        "implemented_input_checks": validation,
        "ideal_kinematics": VerificationItem(
            state=VerificationState.PARTIAL,
            summary="Ideal lossless ratio, speed, and torque relationships are calculated; losses and performance criteria are excluded.",
            evidence=["No efficiency, load rating, or acceptance threshold is modeled."],
        ),
        "involute_geometry": VerificationItem(
            state=VerificationState.WARNING,
            summary="Sampled mathematical involute flanks with an approximate straight radial root connector; valid solid construction does not establish correct tooth engagement.",
            evidence=["Spline-interpolated flanks; no contact, interference, strength, or manufacturing checks."],
        ),
        "tooth_strength": VerificationItem(
            state=VerificationState.UNKNOWN,
            summary="Strength is unknown because required materials, geometry factors, and criteria are not modeled.",
            evidence=["No bending or contact stress calculation is implemented."],
        ),
        "tooth_contact": VerificationItem(
            state=VerificationState.UNKNOWN,
            summary="The profile uses involute flanks, but contact path, conjugate motion and interference have not been verified.",
            evidence=["Pressure angle is a geometry input; no contact ratio, backlash, or interference analysis is implemented."],
        ),
        "thermal_analysis": VerificationItem(
            state=VerificationState.UNTESTED,
            summary="No thermal analysis is implemented.",
        ),
        "service_conditions": VerificationItem(
            state=VerificationState.UNOBSERVABLE,
            summary="Duty cycle, lubrication, environment, mounting, and measured operating conditions are not supplied.",
        ),
    }
