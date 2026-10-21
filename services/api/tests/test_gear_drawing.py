from fastapi.testclient import TestClient

from aeropkmech import store
from aeropkmech.families import get_family
from aeropkmech.main import app


def test_gear_reference_drawing_is_revision_bound_and_retained(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "data" / "project.json")
    monkeypatch.setattr("aeropkmech.main.ARTIFACTS", tmp_path / "artifacts")
    client = TestClient(app)
    before = client.get("/api/v1/project").json()

    drawing = client.get("/api/v1/gear/layout.pdf")
    assert drawing.status_code == 200
    assert drawing.headers["content-type"].startswith("application/pdf")
    assert drawing.content.startswith(b"%PDF-")
    assert drawing.headers["x-design-revision"] == str(before["revision"])
    assert drawing.headers["x-generator-version"] == "gear-reference-drawing-0.1"
    assert drawing.headers["x-artifact-id"].startswith("gear-reference-drawing:r1:")
    assert drawing.headers["x-artifact-sha256"]
    assert client.get("/api/v1/project").json() == before

    metadata = next(item for item in client.get("/api/v1/artifacts").json()["artifacts"] if item["kind"] == "gear-reference-drawing")
    assert metadata["dependencies"] == [
        {"key": "spur_gear_pair:requirements", "revision": before["revision"]},
        {"key": "assembly_geometry", "revision": before["revision"]},
        {"key": "engineering_calculations", "revision": before["revision"]},
    ]
    client.patch("/api/v1/project", json={"module_mm": 2.5, "expected_revision": before["revision"]})
    stale = next(item for item in client.get("/api/v1/artifacts").json()["artifacts"] if item["kind"] == "gear-reference-drawing")
    assert stale["stale"] is True
    retained = client.get(f"/api/v1/artifacts/{metadata['filename']}")
    assert retained.status_code == 200
    assert retained.headers["x-artifact-stale"] == "true"


def test_gear_drawing_rejects_vehicle_family_without_mutation(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "data" / "project.json")
    client = TestClient(app)
    vehicle = get_family("electric_vehicle", "1.0").default_design()
    monkeypatch.setattr(store, "load", lambda: vehicle)
    rejected = client.get("/api/v1/gear/layout.pdf")
    assert rejected.status_code == 409
    assert not (tmp_path / "artifacts").exists()
