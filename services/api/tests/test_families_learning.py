import math

from fastapi.testclient import TestClient
import pytest

from aeropkmech import store
from aeropkmech.families import UnsupportedDesignFamily, get_family, list_families
from aeropkmech.main import app


def isolate_project(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "data" / "project.json")
    return TestClient(app)


def test_spur_gear_family_is_registered_and_version_checked():
    families = list_families()
    assert [family.id for family in families] == ["spur_gear_pair", "electric_vehicle"]
    assert families[0].schema_version == "1.0"
    assert "sampled mathematical involute CAD" in families[0].capabilities
    assert {item["type"] for item in families[0].exporters} == {"step", "stl", "html", "pdf"}
    assert any("tooth contact: UNOBSERVABLE" in item for item in families[0].verification_checks)
    assert any("tooth strength: UNKNOWN" in item for item in families[0].verification_checks)
    assert families[1].schema_version == "1.0"
    assert "layout drawing PDF" in families[1].capabilities
    with pytest.raises(UnsupportedDesignFamily, match="not implemented"):
        get_family("aerospace_wing")
    with pytest.raises(UnsupportedDesignFamily, match="schema version"):
        get_family("spur_gear_pair", "9.0")


def test_family_discovery_is_read_only_and_initialization_is_explicit(tmp_path, monkeypatch):
    client = isolate_project(tmp_path, monkeypatch)
    original = client.get("/api/v1/project").json()
    discover = client.get("/api/v1/design-families").json()
    assert [item["id"] for item in discover["families"]] == ["spur_gear_pair", "electric_vehicle"]
    assert "Aerospace and aerodynamics" in discover["planned_areas"]
    assert client.get("/api/v1/project").json() == original

    invalid = client.post("/api/v1/project/initialize", json={"family_id": "aerospace_wing"})
    assert invalid.status_code == 422
    assert client.get("/api/v1/project").json() == original

    initialized = client.post("/api/v1/project/initialize", json={"family_id": "spur_gear_pair", "schema_version": "1.0"})
    assert initialized.status_code == 200
    design = initialized.json()
    assert design["family"] == "spur_gear_pair"
    assert design["schema_version"] == "1.0"
    assert design["revision"] == original["revision"] + 1
    assert design["id"].startswith("local-")
    assert design["history"][-1]["revision"] == original["revision"]
    restored = client.post("/api/v1/project/demo").json()
    assert restored["revision"] == design["revision"] + 1
    assert restored["id"] == "demo-gearbox"
    assert restored["components"][0]["teeth"] == 18
    vehicle=client.post("/api/v1/project/initialize",json={"family_id":"electric_vehicle","schema_version":"1.0"})
    assert vehicle.status_code==200
    assert vehicle.json()["family"]=="electric_vehicle"
    assert vehicle.json()["revision"]==restored["revision"]+1
    assert vehicle.json()["derived"]["calculation_status"]["range"]=="UNRESOLVED"


def test_12_30_reference_edit_and_failure_preserve_revision(tmp_path, monkeypatch):
    client = isolate_project(tmp_path, monkeypatch)
    original = client.get("/api/v1/project").json()
    result = client.patch("/api/v1/project", json={
        "pinion_teeth": 12, "gear_teeth": 30, "module_mm": 2,
        "face_width_mm": 12, "input_torque_Nm": 8, "input_speed_rpm": 900,
    })
    assert result.status_code == 200
    project = result.json()
    assert project["derived"]["gear_ratio"] == 2.5
    assert project["derived"]["center_distance_mm"] == 42
    assert project["derived"]["output_speed_rpm"] == 360
    assert project["derived"]["ideal_output_torque_Nm"] == 20
    assert project["calculations"]["provenance"]["design_revision"] == project["revision"]
    assert all(item["design_revision"] == project["revision"] for item in project["calculations"]["results"])

    invalid = client.patch("/api/v1/project", json={"face_width_mm": 0})
    assert invalid.status_code == 422
    after = client.get("/api/v1/project").json()
    assert after["revision"] == project["revision"] == original["revision"] + 1
    assert after["requirements"] == project["requirements"]
    assert after["derived"] == project["derived"]


def test_learning_experiment_uses_shared_core_without_mutating_project(tmp_path, monkeypatch):
    client = isolate_project(tmp_path, monkeypatch)
    original = client.get("/api/v1/project").json()
    result = client.post("/api/v1/learn/spur-gear/experiment", json={
        "pinion_teeth": 12, "gear_teeth": 30, "module_mm": 2,
        "face_width_mm": 12, "pressure_angle_deg": 25, "input_torque_Nm": 8, "input_speed_rpm": 900,
    })
    assert result.status_code == 200
    data = result.json()
    assert data["derived"]["gear_ratio"] == 2.5
    assert data["derived"]["center_distance_mm"] == 42
    assert data["derived"]["output_speed_rpm"] == 360
    assert data["derived"]["ideal_output_torque_Nm"] == 20
    assert data["derived"]["pressure_angle_deg"] == 25
    assert math.isclose(data["derived"]["pinion_base_diameter_mm"], 24 * math.cos(math.radians(25)), rel_tol=0, abs_tol=1e-12)
    assert data["calculations"]["provenance"]["design_revision"] is None
    assert data["calculations"]["provenance"]["source_revision"] == original["revision"]
    assert client.get("/api/v1/project").json() == original
    assert client.post("/api/v1/learn/spur-gear/experiment", json={"pinion_teeth": 7}).status_code == 422


def test_live_openapi_contract_describes_real_routes():
    schema = TestClient(app).get("/api/v1/platform/openapi").json()
    assert "/api/v1/project" in schema["paths"]
    assert "patch" in schema["paths"]["/api/v1/project"]
    assert "/api/v1/learn/spur-gear/experiment" in schema["paths"]
    assert "/api/v1/platform/openapi" not in schema["paths"]
