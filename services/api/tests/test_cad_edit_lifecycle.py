"""End-to-end verification of the CAD edit lifecycle for spur gear and EV workflows.

Covers:
- Natural-language edit proposal parsing with dependency tracing
- Structured review card contracts (old/new, delta, affected components, validation checks)
- Explicit accept & commit advancing project revisions and updating CAD/derived state
- Proposal rejection leaving canonical state unchanged
- Invalid edit validation rejection preventing state mutation
- Field-specific grounding verdicts returned by /api/v1/project/interpret
"""
from fastapi.testclient import TestClient
import pytest

from aeropkmech.main import app
from aeropkmech import store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "data" / "project.json")
    monkeypatch.setattr("aeropkmech.main.ARTIFACTS", tmp_path / "artifacts")
    return TestClient(app)


def test_gear_cad_edit_lifecycle_accept_and_commit(client):
    # 1. Initialize spur gear project
    init_res = client.post("/api/v1/project/initialize", json={"family_id": "spur_gear_pair"})
    assert init_res.status_code == 200
    initial = init_res.json()
    init_rev = initial["revision"]
    curr_mod = initial["requirements"]["module_mm"]

    # 2. Propose parameter edit via natural language
    prop_res = client.post(
        "/api/v1/project/propose-edit",
        json={"text": "Set module to 2.5 mm", "expected_revision": init_rev},
    )
    assert prop_res.status_code == 200
    proposal = prop_res.json()
    assert proposal["matched"] is True
    assert proposal["parameter_name"] == "module_mm"
    assert proposal["old_value"] == curr_mod
    assert proposal["proposed_value"] == 2.5
    assert proposal["delta"] == 2.5 - curr_mod
    assert proposal["unit"] == "mm"
    assert proposal["validation_passed"] is True
    assert proposal["can_commit"] is True
    assert "pinion" in proposal["affected_components"]
    assert "gear" in proposal["affected_components"]
    assert "center_distance_mm" in proposal["affected_dependencies"]
    assert "range_boundary" in proposal["validation_checks"]
    assert proposal["validation_checks"]["range_boundary"] == "PASSED"

    # Canonical state is not mutated before commit
    state_before = client.get("/api/v1/project").json()
    assert state_before["revision"] == init_rev
    assert state_before["requirements"]["module_mm"] == curr_mod

    # 3. Accept & commit proposal
    commit_res = client.patch(
        "/api/v1/project",
        json={"module_mm": proposal["proposed_value"], "expected_revision": init_rev},
    )
    assert commit_res.status_code == 200
    updated = commit_res.json()
    assert updated["revision"] == init_rev + 1
    assert updated["requirements"]["module_mm"] == 2.5
    # Verify derived pitch diameter updated: 18 * 2.5 = 45.0 mm
    assert updated["derived"]["pinion_pitch_diameter_mm"] == 45.0
    assert updated["derived"]["center_distance_mm"] == (18 + 54) * 2.5 / 2.0  # 90.0 mm

    # 4. STL export succeeds for the new revision
    stl_res = client.get("/api/v1/export/stl")
    assert stl_res.status_code == 200
    assert len(stl_res.content) > 100


def test_gear_cad_bore_keyway_lifecycle(client):
    init_res = client.post("/api/v1/project/initialize", json={"family_id": "spur_gear_pair"})
    initial = init_res.json()
    init_rev = initial["revision"]

    # Propose bore edit
    bore_prop = client.post(
        "/api/v1/project/propose-edit",
        json={"text": "Set shaft bore to 16 mm", "expected_revision": init_rev},
    ).json()
    assert bore_prop["matched"] is True
    assert bore_prop["parameter_name"] == "bore_diameter_mm"
    assert bore_prop["proposed_value"] == 16.0
    assert bore_prop["can_commit"] is True

    # Commit bore edit -> advances revision
    commit_bore = client.patch(
        "/api/v1/project",
        json={"bore_diameter_mm": 16.0, "expected_revision": init_rev},
    ).json()
    rev2 = commit_bore["revision"]
    assert rev2 == init_rev + 1
    assert commit_bore["requirements"]["bore_diameter_mm"] == 16.0

    # Test DIN 6885 cross-field invariant: only keyway width without depth must be rejected
    solo_kw = client.patch(
        "/api/v1/project",
        json={"keyway_width_mm": 5.0, "expected_revision": rev2},
    )
    assert solo_kw.status_code == 422
    assert "Both keyway_width_mm and keyway_depth_mm must be provided together" in solo_kw.json()["detail"]

    # Commit both keyway width and depth together -> advances revision
    commit_kw = client.patch(
        "/api/v1/project",
        json={"keyway_width_mm": 5.0, "keyway_depth_mm": 2.3, "expected_revision": rev2},
    ).json()
    assert commit_kw["revision"] == rev2 + 1
    assert commit_kw["requirements"]["keyway_width_mm"] == 5.0
    assert commit_kw["requirements"]["keyway_depth_mm"] == 2.3


def test_gear_invalid_edit_rejected_no_state_mutation(client):
    init_res = client.post("/api/v1/project/initialize", json={"family_id": "spur_gear_pair"})
    initial_rev = init_res.json()["revision"]

    # Propose negative face width
    prop = client.post(
        "/api/v1/project/propose-edit",
        json={"text": "Set face width to -5 mm", "expected_revision": initial_rev},
    ).json()
    assert prop["can_commit"] is False or prop["validation_passed"] is False

    # Attempting to PATCH invalid face width fails with 422
    patch_res = client.patch(
        "/api/v1/project",
        json={"face_width_mm": -5.0, "expected_revision": initial_rev},
    )
    assert patch_res.status_code == 422

    # Verify state was not mutated
    current = client.get("/api/v1/project").json()
    assert current["revision"] == initial_rev
    assert current["requirements"]["face_width_mm"] > 0


def test_ev_cad_edit_lifecycle(client):
    # 1. Initialize EV design via supported family initialization
    init_res = client.post("/api/v1/project/initialize", json={"family_id": "electric_vehicle"})
    assert init_res.status_code == 200
    ev = init_res.json()
    assert ev["family"] == "electric_vehicle"
    ev_rev = ev["revision"]
    initial_wb = ev["requirements"]["wheelbase_mm"]["value"]

    # 2. Propose wheelbase edit via natural language
    prop = client.post(
        "/api/v1/project/propose-edit",
        json={"text": "Increase wheelbase to 2800 mm", "expected_revision": ev_rev},
    ).json()
    assert prop["matched"] is True
    assert prop["parameter_name"] == "wheelbase_mm"
    assert prop["old_value"] == initial_wb
    assert prop["proposed_value"] == 2800.0
    assert prop["delta"] == 2800.0 - initial_wb
    assert prop["can_commit"] is True

    # 3. Commit EV wheelbase edit -> advances revision
    patch_res = client.patch(
        "/api/v1/project/vehicle",
        json={"wheelbase_mm": 2800.0, "expected_revision": ev_rev},
    )
    assert patch_res.status_code == 200
    updated_ev = patch_res.json()
    assert updated_ev["revision"] == ev_rev + 1
    assert updated_ev["requirements"]["wheelbase_mm"]["value"] == 2800.0

    # 4. Check out-of-range wheelbase is rejected
    rej_res = client.patch(
        "/api/v1/project/vehicle",
        json={"wheelbase_mm": 500.0, "expected_revision": updated_ev["revision"]},
    )
    assert rej_res.status_code == 422
    assert client.get("/api/v1/project").json()["revision"] == updated_ev["revision"]


def test_interpret_surfaces_structured_field_grounding(client):
    res = client.post(
        "/api/v1/project/interpret",
        json={
            "text": "External spur gear pair: pinion 18 teeth, driven gear 54 teeth, module 2.5 mm, face width 30 mm, torque 120 Nm, speed 1450 rpm."
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "field_grounding" in data
    fg = data["field_grounding"]

    # Verify structured GroundingVerdict fields
    assert fg["pinion_teeth"]["source_class"] == "EXPLICIT"
    assert fg["gear_teeth"]["source_class"] == "EXPLICIT"
    assert fg["module_mm"]["source_class"] == "EXPLICIT"
    assert fg["gear_ratio"]["source_class"] in {"DERIVED", "EXPLICIT"}
    assert fg["pressure_angle_deg"]["source_class"] in {"ASSUMED", "EXPLICIT"}
    assert fg["bore_diameter_mm"]["source_class"] in {"MISSING", "ASSUMED"}
