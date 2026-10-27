from fastapi.testclient import TestClient
import pytest

from aeropkmech.main import app
from aeropkmech import store
from aeropkmech.intelligence import propose_parameter_edit


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "data" / "project.json")
    monkeypatch.setattr("aeropkmech.main.ARTIFACTS", tmp_path / "artifacts")
    return TestClient(app)


def test_gear_direct_parameter_edit_proposal(client):
    client.post("/api/v1/project/demo")
    current = store.load()
    
    # Direct module change
    res = client.post("/api/v1/project/propose-edit", json={"text": "Increase gear module to 2.5 mm", "expected_revision": current.revision})
    assert res.status_code == 200
    data = res.json()
    assert data["matched"] is True
    assert data["parameter_name"] == "module_mm"
    assert data["proposed_value"] == 2.5
    assert data["unit"] == "mm"
    assert data["validation_passed"] is True
    assert data["can_commit"] is True
    assert "pinion" in data["affected_components"]
    assert "center_distance_mm" in data["affected_dependencies"]


def test_gear_relative_parameter_edit_proposal(client):
    client.post("/api/v1/project/demo")
    current = store.load()
    initial_pinion = current.components[0].teeth  # 18
    
    res = client.post("/api/v1/project/propose-edit", json={"text": "Add 2 teeth to pinion", "expected_revision": current.revision})
    assert res.status_code == 200
    data = res.json()
    assert data["matched"] is True
    assert data["parameter_name"] == "pinion_teeth"
    assert data["proposed_value"] == initial_pinion + 2
    assert data["validation_passed"] is True
    assert data["can_commit"] is True


def test_gear_out_of_bounds_edit_rejected(client):
    client.post("/api/v1/project/demo")
    current = store.load()
    
    res = client.post("/api/v1/project/propose-edit", json={"text": "Change pinion teeth to 150", "expected_revision": current.revision})
    assert res.status_code == 200
    data = res.json()
    assert data["matched"] is True
    assert data["validation_passed"] is False
    assert data["can_commit"] is False
    assert "exceeds maximum" in data["validation_error"]


def test_ev_direct_and_unit_normalized_edit(client):
    # Initialize EV
    init_res = client.post("/api/v1/project/initialize", json={"family_id": "electric_vehicle", "schema_version": "1.0"})
    assert init_res.status_code == 200
    current = store.load()
    assert current.family == "electric_vehicle"
    
    # Wheelbase edit
    res = client.post("/api/v1/project/propose-edit", json={"text": "Change wheelbase to 2700 mm", "expected_revision": current.revision})
    assert res.status_code == 200
    data = res.json()
    assert data["matched"] is True
    assert data["parameter_name"] == "wheelbase_mm"
    assert data["proposed_value"] == 2700.0
    assert data["can_commit"] is True
    assert "front/rear axles" in data["affected_dependencies"]

    # Unit conversion from meters
    res2 = client.post("/api/v1/project/propose-edit", json={"text": "Make overall length 4.4 m", "expected_revision": current.revision})
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["matched"] is True
    assert data2["parameter_name"] == "overall_length_mm"
    assert data2["proposed_value"] == 4400.0
    assert data2["can_commit"] is True


def test_ev_battery_pack_movement_guidance(client):
    client.post("/api/v1/project/initialize", json={"family_id": "electric_vehicle", "schema_version": "1.0"})
    current = store.load()
    
    res = client.post("/api/v1/project/propose-edit", json={"text": "Move the battery pack 20 mm rearward", "expected_revision": current.revision})
    assert res.status_code == 200
    data = res.json()
    assert data["matched"] is True
    assert data["can_commit"] is False
    assert "battery pack envelope placement" in data["explanation"]
    assert "wheelbase" in data["explanation"]


def test_unsupported_edit_request(client):
    client.post("/api/v1/project/demo")
    current = store.load()
    
    res = client.post("/api/v1/project/propose-edit", json={"text": "Change drone propeller pitch to 12 inches", "expected_revision": current.revision})
    assert res.status_code == 200
    data = res.json()
    assert data["matched"] is False
    assert data["can_commit"] is False


def test_edit_proposal_revision_conflict(client):
    client.post("/api/v1/project/demo")
    current = store.load()
    
    res = client.post("/api/v1/project/propose-edit", json={"text": "Increase module to 2.5 mm", "expected_revision": current.revision + 5})
    assert res.status_code == 409


def test_hub_parameter_edit_proposal_and_patch(client):
    from aeropkmech.cad import build_assembly
    client.post("/api/v1/project/demo")
    current = store.load()

    # Propose hub diameter change via NL
    res = client.post("/api/v1/project/propose-edit", json={"text": "Set hub diameter to 25 mm", "expected_revision": current.revision})
    assert res.status_code == 200
    data = res.json()
    assert data["matched"] is True
    assert data["parameter_name"] == "hub_diameter_mm"
    assert data["proposed_value"] == 25.0
    assert data["unit"] == "mm"
    assert data["can_commit"] is True

    # Patch both hub diameter and length into canonical project state
    patch_res = client.patch("/api/v1/project", json={"hub_diameter_mm": 25.0, "hub_length_mm": 12.0})
    assert patch_res.status_code == 200
    patched = patch_res.json()
    assert patched["revision"] == current.revision + 1
    assert patched["requirements"]["hub_diameter_mm"] == 25.0
    assert patched["requirements"]["hub_length_mm"] == 12.0
    assert "hub_diameter_mm" in patched["parameter_quantities"]
    assert "hub_length_mm" in patched["parameter_quantities"]

    # Verify CAD geometry builds with the fused boss
    assembly = build_assembly(store.load())
    assert len(assembly.children) == 2
    assert all(part.obj.val().isValid() for part in assembly.children)

