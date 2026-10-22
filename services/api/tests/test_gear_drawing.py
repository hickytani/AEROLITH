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
    assert drawing.headers["x-generator-version"] == "gear-reference-drawing-0.3"
    assert drawing.headers["x-artifact-id"].startswith("gear-reference-drawing:r1:")
    assert drawing.headers["x-artifact-sha256"]
    assert client.get("/api/v1/project").json() == before

    metadata = next(item for item in client.get("/api/v1/artifacts").json()["artifacts"] if item["kind"] == "gear-reference-drawing")
    assert set(metadata["parameter_ids"]) == {record["id"] for record in before["parameter_records"].values()}
    assert metadata["design_sha256"]
    assert b"spur_gear_pair@1.0" in drawing.content
    assert b"demo-gearbox:module_mm" in drawing.content
    assert b"Trace IDs:" in drawing.content
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


def test_failed_step_regeneration_keeps_prior_verified_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "data" / "project.json")
    monkeypatch.setattr("aeropkmech.main.ARTIFACTS", tmp_path / "artifacts")
    client = TestClient(app)
    original = client.get("/api/v1/export/step")
    assert original.status_code == 200 and original.content.startswith(b"ISO-10303-21;")
    index_before = client.get("/api/v1/artifacts").json()
    artifact_before = next(item for item in index_before["artifacts"] if item["kind"] == "assembly" and item["filename"].endswith(".step"))
    path = tmp_path / "artifacts" / artifact_before["filename"]
    original_bytes = path.read_bytes()

    def fail_export(_design, target):
        target.write_bytes(b"partial broken STEP")
        raise RuntimeError("simulated CAD export failure")

    monkeypatch.setattr("aeropkmech.main.cad.export_step", fail_export)
    failed = client.get("/api/v1/export/step")
    assert failed.status_code == 500
    assert failed.json()["verification"]["state"] == "EXECUTION_ERROR"
    index_after = client.get("/api/v1/artifacts").json()
    assert index_after == index_before
    assert path.read_bytes() == original_bytes
    assert not list((tmp_path / "artifacts").glob(".generating-*.step"))
