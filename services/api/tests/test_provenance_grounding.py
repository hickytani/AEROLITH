"""Sprint 7: Engineering Provenance, Grounding Verdicts & Source Traceability Tests.

Verifies:
1. EXPLICIT: User-supplied parameters retain exact text spans and evidence.
2. DERIVED: Calculated parameters (e.g., gear ratio from teeth) retain mathematical derivations.
3. ASSUMED: Default values (e.g., 20° pressure angle) carry explicit assumption reasoning.
4. MISSING: Omitted parameters are classified as MISSING without silent invention.
5. CONTRADICTION: Conflicting explicit values yield CONTRADICTION status, clear values, and prevent commit.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aeropkmech.main import app
from aeropkmech.intelligence import assess_field_grounding, extract_local, propose_specification


@pytest.fixture
def client():
    return TestClient(app)


def test_explicit_parameters_surface_grounding_and_span(client: TestClient):
    """Explicitly mentioned values must be classified as EXPLICIT with exact evidence spans."""
    prompt = "Design a spur gear pair. Pinion has 18 teeth, gear has 54 teeth. Module 2 mm, face width 20 mm."
    
    # Check /api/v1/project/interpret endpoint
    res = client.post("/api/v1/project/interpret", json={"text": prompt})
    assert res.status_code == 200
    data = res.json()
    assert "field_grounding" in data
    fg = data["field_grounding"]
    
    for field in ["module_mm", "face_width_mm", "pinion_teeth", "gear_teeth"]:
        assert fg[field]["source_class"] == "EXPLICIT", f"{field} should be EXPLICIT"
        assert fg[field]["evidence_span"] is not None

    # Check /api/v1/specifications/propose endpoint
    spec_res = client.post("/api/v1/specifications/propose", json={"text": prompt})
    assert spec_res.status_code == 200
    spec = spec_res.json()
    param_map = {p["name"]: p for p in spec["parameters"]}
    
    assert param_map["module_mm"]["source"] == "user-provided"
    assert param_map["module_mm"]["status"] == "PROPOSED"
    assert param_map["module_mm"]["value"] == 2.0
    assert param_map["module_mm"]["evidence"] is not None


def test_derived_parameters_surface_reasoning_and_derivation(client: TestClient):
    """Parameters computed from other inputs must be classified as DERIVED with derivation notes."""
    prompt = "Design a spur gear pair. Pinion has 18 teeth, gear has 54 teeth. Module 2 mm, face width 20 mm."
    
    # Interpret endpoint
    res = client.post("/api/v1/project/interpret", json={"text": prompt})
    assert res.status_code == 200
    fg = res.json()["field_grounding"]
    
    assert fg["gear_ratio"]["source_class"] == "DERIVED"
    assert "teeth" in fg["gear_ratio"]["reason"].lower() or "ratio" in fg["gear_ratio"]["reason"].lower() or "derived" in fg["gear_ratio"]["reason"].lower()

    # Propose specification endpoint
    spec_res = client.post("/api/v1/specifications/propose", json={"text": prompt})
    assert spec_res.status_code == 200
    spec = spec_res.json()
    param_map = {p["name"]: p for p in spec["parameters"]}
    
    assert param_map["gear_ratio"]["source"] == "derived"
    assert param_map["gear_ratio"]["status"] == "DERIVED"
    assert param_map["gear_ratio"]["value"] == 3.0
    assert param_map["gear_ratio"]["derivation"] is not None
    assert "54 / 18" in param_map["gear_ratio"]["derivation"] or "teeth" in param_map["gear_ratio"]["derivation"]


def test_assumed_parameters_surface_assumed_status_and_note(client: TestClient):
    """Omitted optional/standard defaults must be marked ASSUMED with their basis note."""
    prompt = "Design a spur gear pair. Pinion 18 teeth, gear 54 teeth, module 2 mm, face width 20 mm."
    
    # Interpret endpoint: pressure_angle_deg omitted -> ASSUMED
    res = client.post("/api/v1/project/interpret", json={"text": prompt})
    assert res.status_code == 200
    fg = res.json()["field_grounding"]
    
    assert fg["pressure_angle_deg"]["source_class"] == "ASSUMED"
    assert "20" in fg["pressure_angle_deg"]["reason"]

    # Propose specification endpoint
    spec_res = client.post("/api/v1/specifications/propose", json={"text": prompt})
    assert spec_res.status_code == 200
    spec = spec_res.json()
    param_map = {p["name"]: p for p in spec["parameters"]}
    
    assert param_map["pressure_angle_deg"]["source"] == "assumed"
    assert param_map["pressure_angle_deg"]["status"] == "ASSUMED"
    assert param_map["pressure_angle_deg"]["value"] == 20.0


def test_missing_required_parameters_surface_missing_status(client: TestClient):
    """Missing required dimensions must be classified as MISSING without fabricating values."""
    # Omit pinion_teeth
    prompt = "Design a spur gear pair. Gear has 54 teeth, module 2 mm, face width 20 mm."
    
    res = client.post("/api/v1/project/interpret", json={"text": prompt})
    assert res.status_code == 200
    fg = res.json()["field_grounding"]
    
    assert fg["pinion_teeth"]["source_class"] == "MISSING"

    spec_res = client.post("/api/v1/specifications/propose", json={"text": prompt})
    assert spec_res.status_code == 200
    spec = spec_res.json()
    param_map = {p["name"]: p for p in spec["parameters"]}
    
    assert param_map["pinion_teeth"]["source"] == "missing"
    assert param_map["pinion_teeth"]["status"] == "MISSING"
    assert param_map["pinion_teeth"]["value"] is None
    assert spec["can_commit"] is False


def test_contradiction_parameters_surface_contradiction_verdict_and_clear_value(client: TestClient):
    """Conflicting explicit inputs must yield CONTRADICTION verdict, clear value, and prevent commit."""
    prompt = "Design a spur gear pair. Pinion 18 teeth, gear 54 teeth, module 2 mm and module 3 mm, face width 20 mm."
    
    # Direct assess_field_grounding check
    extraction = extract_local(prompt)
    assert any("module_mm" in c for c in extraction.conflicts)
    verdict = assess_field_grounding("module_mm", extraction.proposal.module_mm, prompt, extraction)
    assert verdict.source_class == "CONTRADICTION"
    assert "conflicting" in verdict.reason.lower()

    # Interpret endpoint
    res = client.post("/api/v1/project/interpret", json={"text": prompt})
    assert res.status_code == 200
    fg = res.json()["field_grounding"]
    assert fg["module_mm"]["source_class"] == "CONTRADICTION"

    # Propose specification endpoint
    spec_res = client.post("/api/v1/specifications/propose", json={"text": prompt})
    assert spec_res.status_code == 200
    spec = spec_res.json()
    param_map = {p["name"]: p for p in spec["parameters"]}
    
    assert param_map["module_mm"]["status"] == "CONTRADICTION"
    assert param_map["module_mm"]["value"] is None  # Never emit a misleading contradicted value
    assert spec["can_commit"] is False
    assert len(spec["conflicts"]) > 0
