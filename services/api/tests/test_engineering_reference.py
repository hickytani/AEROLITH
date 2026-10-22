"""Numerical reference cases computed independently from the demo implementation.

The expected results below are manually evaluated reference values using the
documented ideal relationships. They are deliberately constants so a regression
in the implementation formula cannot update its own expected result.
"""

import pytest

from aeropkmech.domain import Component, Design, EditRequest, Requirements
from aeropkmech.engineering import derive
from aeropkmech.intelligence import extract_local
from aeropkmech.store import default_design
from aeropkmech.verification import VerificationState, summarize


@pytest.mark.parametrize(
    ("pinion_teeth", "gear_teeth", "module_mm", "face_width_mm", "speed_rpm", "torque_nm", "expected"),
    [
        (18, 54, 2.0, 12.0, 900.0, 8.0, {
            "gear_ratio": 3.0,
            "pinion_pitch_diameter_mm": 36.0,
            "gear_pitch_diameter_mm": 108.0,
            "center_distance_mm": 72.0,
            "output_speed_rpm": 300.0,
            "ideal_output_torque_Nm": 24.0,
            "pinion_outer_diameter_mm": 40.0,
            "gear_outer_diameter_mm": 112.0,
        }),
        (20, 40, 1.5, 8.0, 1500.0, 3.2, {
            "gear_ratio": 2.0,
            "pinion_pitch_diameter_mm": 30.0,
            "gear_pitch_diameter_mm": 60.0,
            "center_distance_mm": 45.0,
            "output_speed_rpm": 750.0,
            "ideal_output_torque_Nm": 6.4,
            "pinion_outer_diameter_mm": 33.0,
            "gear_outer_diameter_mm": 63.0,
        }),
    ],
)
def test_ideal_relationships_match_independent_reference_values(
    pinion_teeth, gear_teeth, module_mm, face_width_mm, speed_rpm, torque_nm, expected
):
    design = Design(
        revision=1,
        requirements=Requirements(
            gear_ratio=gear_teeth / pinion_teeth,
            input_torque_Nm=torque_nm,
            input_speed_rpm=speed_rpm,
            module_mm=module_mm,
            face_width_mm=face_width_mm,
        ),
        assumptions=["Test-only ideal lossless reference case."],
        components=[
            Component(id="pinion", name="Pinion", teeth=pinion_teeth),
            Component(id="gear", name="Driven gear", teeth=gear_teeth),
        ],
        status={},
    )
    results = derive(design)
    for name, reference in expected.items():
        assert results[name] == pytest.approx(reference, rel=0, abs=1e-9)


@pytest.mark.parametrize(
    "changes",
    [
        {"pinion_teeth": 7},
        {"pinion_teeth": 81},
        {"gear_teeth": 7},
        {"gear_teeth": 121},
        {"module_mm": 0.49},
        {"module_mm": 6.01},
        {"face_width_mm": 1.99},
        {"face_width_mm": 60.01},
        {"input_speed_rpm": 0},
        {"input_torque_Nm": 0},
        {"input_speed_rpm": float("inf")},
        {"input_torque_Nm": float("nan")},
        {"unknown_field": 1},
        {},
    ],
)
def test_invalid_edits_are_rejected_by_request_contract(changes):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EditRequest.model_validate(changes)


@pytest.mark.parametrize(
    ("pinion_teeth", "gear_teeth", "module_mm", "face_width_mm"),
    [(8, 8, 0.5, 2.0), (80, 120, 6.0, 60.0)],
)
def test_supported_input_boundaries_are_accepted(pinion_teeth, gear_teeth, module_mm, face_width_mm):
    assert EditRequest.model_validate({
        "pinion_teeth": pinion_teeth,
        "gear_teeth": gear_teeth,
        "module_mm": module_mm,
        "face_width_mm": face_width_mm,
    })


def test_explicit_torque_unit_conversion_matches_reference():
    proposal = extract_local("input torque 8000 Nmm")
    assert proposal.proposal.input_torque_Nm == pytest.approx(8.0, abs=1e-12)


def test_missing_strength_inputs_never_yield_a_verification_pass():
    verification = summarize(default_design())
    assert verification["overall"].state == VerificationState.PARTIAL
    assert "not a safety finding" in verification["overall"].summary
    assert verification["tooth_strength"].state == VerificationState.UNKNOWN
    assert verification["tooth_contact"].state == VerificationState.UNKNOWN
    assert verification["thermal_analysis"].state == VerificationState.UNTESTED
    assert verification["service_conditions"].state == VerificationState.UNOBSERVABLE


def test_failed_implemented_check_is_not_reported_as_passed():
    inconsistent = default_design().model_copy(deep=True)
    inconsistent.requirements.gear_ratio = 9
    verification = summarize(inconsistent)
    assert verification["overall"].state == VerificationState.FAILED
    assert verification["implemented_input_checks"].state == VerificationState.FAILED
    assert verification["tooth_strength"].state == VerificationState.UNKNOWN


def test_mixed_verification_states_never_collapse_to_overall_pass():
    verification = summarize(default_design())
    assert verification["implemented_input_checks"].state == VerificationState.PASSED
    assert verification["involute_geometry"].state == VerificationState.WARNING
    assert verification["ideal_kinematics"].state == VerificationState.PARTIAL
    assert verification["tooth_strength"].state == VerificationState.UNKNOWN
    assert verification["thermal_analysis"].state == VerificationState.UNTESTED
    assert verification["service_conditions"].state == VerificationState.UNOBSERVABLE
    assert verification["overall"].state != VerificationState.PASSED
