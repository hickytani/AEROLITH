import json

from fastapi.testclient import TestClient
import pytest

from aeropkmech import store
from aeropkmech.cad import build_assembly
from aeropkmech.main import app, cad


def test_revision_geometry_exports_and_requirement_intake(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "data" / "project.json")
    monkeypatch.setattr("aeropkmech.main.ARTIFACTS", tmp_path / "artifacts")
    client = TestClient(app)

    response = client.get("/api/v1/project")
    assert response.status_code == 200
    initial = response.json()
    assert initial["derived"]["gear_ratio"] == 3
    assert initial["derived"]["pinion_pitch_diameter_mm"] == 36
    assert initial["derived"]["gear_pitch_diameter_mm"] == 108
    assert initial["derived"]["center_distance_mm"] == 72
    assert initial["derived"]["output_speed_rpm"] == 300
    assert initial["derived"]["ideal_output_torque_Nm"] == 24

    text = "18 teeth pinion, 54 teeth driven gear, module 2 mm, face width 12 mm, torque 8 Nm, speed 900 rpm"
    proposal = client.post("/api/v1/project/interpret", json={"text": text}).json()
    assert proposal["parsed"] is True
    assert proposal["proposal"]["gear_ratio"] == 3
    assert client.get("/api/v1/project").json() == initial  # proposals do not mutate canonical state

    edited = client.patch("/api/v1/project", json={"gear_teeth": 72}).json()
    assert edited["revision"] == 2
    assert edited["derived"]["gear_ratio"] == 4
    assert edited["history"][0]["revision"] == 1
    assert edited["verification"]["tooth_strength"]["state"] == "UNKNOWN"
    assert edited["verification"]["ideal_kinematics"]["state"] == "PARTIAL"
    assert edited["verification"]["polygonal_geometry"]["state"] == "WARNING"
    assert edited["verification"]["overall"]["state"] == "PARTIAL"
    assert "not a safety finding" in edited["verification"]["overall"]["summary"]
    assert client.patch("/api/v1/project", json={"module_mm": 0}).status_code == 422
    after_invalid = client.get("/api/v1/project").json()
    assert after_invalid["revision"] == 2
    assert after_invalid["requirements"]["module_mm"] == 2
    persisted_after_invalid = store.load()
    assert persisted_after_invalid.revision == 2
    assert persisted_after_invalid.components[1].teeth == 72

    assembly = build_assembly(store.load())
    assert len(assembly.children) == 2
    assert assembly.children[0].loc.toTuple()[0] == (0.0, 0.0, 0.0)
    driven_position, driven_rotation = assembly.children[1].loc.toTuple()
    assert driven_position == (90.0, 0.0, 0.0)
    assert abs(driven_rotation[2] - 180 / 72) < 1e-12
    assert all(part.obj.val().isValid() for part in assembly.children)
    assert all(abs(part.obj.val().BoundingBox().zlen - 12) < 1e-6 for part in assembly.children)

    stl = client.get("/api/v1/export/stl")
    assert stl.status_code == 200
    assert stl.headers["x-design-revision"] == "2"
    assert stl.headers["x-generator-version"] == "cq-polygon-approx-0.1"
    assert stl.headers["x-artifact-stale"] == "false"
    assert "r2-cq-polygon-approx-0.1" in stl.headers["content-disposition"]
    assert len(stl.content) > 84
    step = client.get("/api/v1/export/step")
    assert step.status_code == 200
    assert step.content.startswith(b"ISO-10303-21;")
    assert step.headers["x-design-revision"] == "2"
    for component_id in ("pinion", "gear"):
        mesh = client.get(f"/api/v1/geometry/{component_id}.stl?revision=2")
        assert mesh.status_code == 200
        assert mesh.headers["content-type"].startswith("model/stl")
        assert mesh.headers["x-design-revision"] == "2"
        assert mesh.headers["x-geometry-revision"] == "2"
        assert mesh.headers["x-geometry-component-id"] == component_id
        assert mesh.headers["x-geometry-units"] == "mm"
        assert mesh.headers["x-geometry-format"] == "stl"
        assert mesh.headers["x-artifact-id"].startswith(f"{component_id}:r2:")
        assert mesh.headers["x-artifact-sha256"]
        assert mesh.headers["cache-control"] == "no-store"
        assert len(mesh.content) > 84
        triangle_count = int.from_bytes(mesh.content[80:84], "little")
        assert triangle_count > 0
        assert len(mesh.content) == 84 + triangle_count * 50
    stale_mesh = client.get("/api/v1/geometry/pinion.stl?revision=1")
    assert stale_mesh.status_code == 409
    assert stale_mesh.headers["x-design-revision"] == "2"
    html_report = client.get("/api/v1/report")
    assert html_report.status_code == 200
    assert "revision 2" in html_report.text
    assert "engineering-note-0.2" in html_report.text
    assert "No bending or contact stress calculation is implemented." in html_report.text
    assert html_report.headers["x-design-revision"] == "2"
    pdf = client.get("/api/v1/report.pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert pdf.headers["x-design-revision"] == "2"
    assert pdf.headers["x-generator-version"] == "engineering-note-0.2"
    assert "engineering-note-0.2" in pdf.headers["content-disposition"]
    listing = client.get("/api/v1/artifacts").json()
    assert listing["current_revision"] == 2
    assert listing["artifacts"]
    assert all(item["revision"] == 2 and item["stale"] is False for item in listing["artifacts"])
    previous_step = next(item["filename"] for item in listing["artifacts"] if item["kind"] == "assembly" and item["filename"].endswith(".step"))

    client.patch("/api/v1/project", json={"gear_teeth": 60})
    stale = client.get("/api/v1/artifacts").json()
    assert stale["current_revision"] == 3
    assert stale["artifacts"]
    assert all(item["stale"] is True for item in stale["artifacts"])
    old_download = client.get(f"/api/v1/artifacts/{previous_step}")
    assert old_download.status_code == 200
    assert old_download.headers["x-artifact-stale"] == "true"
    (tmp_path / "artifacts" / previous_step).write_bytes(b"tampered")
    tampered = client.get(f"/api/v1/artifacts/{previous_step}")
    assert tampered.status_code == 409
    assert tampered.json()["verification"]["state"] == "FAILED"
    fresh = client.get("/api/v1/export/stl")
    assert fresh.headers["x-design-revision"] == "3"
    assert fresh.headers["x-artifact-stale"] == "false"
    refreshed_mesh = client.get("/api/v1/geometry/pinion.stl?revision=3")
    assert refreshed_mesh.headers["x-design-revision"] == "3"
    assert client.get("/").status_code == 200
    assert client.get("/vendor/build/three.module.js").status_code == 200
    assert client.get("/mesh-loader.js").status_code == 200
    assert client.get("/camera-fit.js").status_code == 200


def test_component_mesh_generation_rejects_revision_change_during_build(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "data" / "project.json")
    monkeypatch.setattr("aeropkmech.main.ARTIFACTS", tmp_path / "artifacts")
    client = TestClient(app)
    initial = client.get("/api/v1/project").json()
    original_export = cad.export_component_stl

    def edit_while_generating(design, component_id, target):
        original_export(design, component_id, target)
        changed = client.patch("/api/v1/project", json={"gear_teeth": 60})
        assert changed.status_code == 200

    monkeypatch.setattr("aeropkmech.main.cad.export_component_stl", edit_while_generating)
    response = client.get(f"/api/v1/geometry/pinion.stl?revision={initial['revision']}")
    assert response.status_code == 409
    assert response.headers["x-design-revision"] == str(initial["revision"] + 1)
    assert client.get("/api/v1/artifacts").json()["artifacts"] == []


def test_component_geometry_failure_is_isolated_to_the_requested_component(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "data" / "project.json")
    monkeypatch.setattr("aeropkmech.main.ARTIFACTS", tmp_path / "artifacts")
    client = TestClient(app)
    original_export = cad.export_component_stl

    def fail_only_gear(design, component_id, target):
        if component_id == "gear":
            raise RuntimeError("gear tessellation failed")
        return original_export(design, component_id, target)

    monkeypatch.setattr("aeropkmech.main.cad.export_component_stl", fail_only_gear)
    pinion = client.get("/api/v1/geometry/pinion.stl?revision=1")
    gear = client.get("/api/v1/geometry/gear.stl?revision=1")
    assert pinion.status_code == 200
    assert pinion.headers["x-geometry-component-id"] == "pinion"
    assert gear.status_code == 500
    assert "gear tessellation failed" in gear.json()["detail"]
    indexed = client.get("/api/v1/artifacts").json()["artifacts"]
    assert [item["kind"] for item in indexed] == ["pinion"]


def test_malformed_project_and_cad_execution_failure_are_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "data" / "project.json")
    monkeypatch.setattr("aeropkmech.main.ARTIFACTS", tmp_path / "artifacts")
    client = TestClient(app)
    assert client.get("/api/v1/project").status_code == 200
    store.STATE_FILE.write_text("not json", encoding="utf-8")
    corrupt = client.get("/api/v1/project")
    assert corrupt.status_code == 503
    assert corrupt.json()["verification"]["state"] == "EXECUTION_ERROR"

    store.save(store.default_design())
    monkeypatch.setattr("aeropkmech.main.cad.export_step", lambda *_: (_ for _ in ()).throw(RuntimeError("kernel error")))
    failed = client.get("/api/v1/export/step")
    assert failed.status_code == 500
    assert failed.json()["verification"]["state"] == "EXECUTION_ERROR"
    assert client.get("/api/v1/artifacts").json()["artifacts"] == []


def test_malformed_artifact_index_is_reported_explicitly(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "data" / "project.json")
    monkeypatch.setattr("aeropkmech.main.ARTIFACTS", tmp_path / "artifacts")
    client = TestClient(app)
    assert client.get("/api/v1/project").status_code == 200
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "artifact-index.json").write_text("{bad", encoding="utf-8")
    response = client.get("/api/v1/artifacts")
    assert response.status_code == 503
    assert response.json()["verification"]["state"] == "EXECUTION_ERROR"


def test_unsafe_artifact_index_filename_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "data" / "project.json")
    artifact_dir = tmp_path / "artifacts"
    monkeypatch.setattr("aeropkmech.main.ARTIFACTS", artifact_dir)
    client = TestClient(app)
    assert client.get("/api/v1/project").status_code == 200
    artifact_dir.mkdir()
    index = {
        "schema_version": 1,
        "artifacts": [{
            "artifact_id": "assembly:r1:bad", "kind": "assembly", "filename": "..\\victim.step", "revision": 1,
            "design_sha256": "0" * 64, "sha256": "0" * 64, "generator_version": "test", "created_at": "test",
        }],
    }
    (artifact_dir / "artifact-index.json").write_text(json.dumps(index), encoding="utf-8")
    assert client.get("/api/v1/artifacts").status_code == 503
    assert client.get("/api/v1/artifacts/..%5Cvictim.step").status_code == 404


@pytest.mark.parametrize(
    ("edit", "expected"),
    [
        ({"pinion_teeth": 16, "gear_teeth": 16, "module_mm": 1, "face_width_mm": 5, "input_speed_rpm": 1200, "input_torque_Nm": 2},
         {"gear_ratio": 1.0, "pinion_pitch_diameter_mm": 16.0, "gear_pitch_diameter_mm": 16.0, "center_distance_mm": 16.0, "output_speed_rpm": 1200.0, "ideal_output_torque_Nm": 2.0}),
        ({"pinion_teeth": 17, "gear_teeth": 53, "module_mm": 1.1, "face_width_mm": 7.5, "input_speed_rpm": 1000, "input_torque_Nm": 5.3},
         {"gear_ratio": 3.1176470588235294, "pinion_pitch_diameter_mm": 18.7, "gear_pitch_diameter_mm": 58.3, "center_distance_mm": 38.5, "output_speed_rpm": 320.7547169811321, "ideal_output_torque_Nm": 16.523529411764706}),
        ({"pinion_teeth": 8, "gear_teeth": 8, "module_mm": 0.5, "face_width_mm": 2, "input_speed_rpm": 120, "input_torque_Nm": 0.5},
         {"gear_ratio": 1.0, "pinion_pitch_diameter_mm": 4.0, "gear_pitch_diameter_mm": 4.0, "center_distance_mm": 4.0, "output_speed_rpm": 120.0, "ideal_output_torque_Nm": 0.5}),
        ({"pinion_teeth": 80, "gear_teeth": 120, "module_mm": 6, "face_width_mm": 60, "input_speed_rpm": 1200, "input_torque_Nm": 4},
         {"gear_ratio": 1.5, "pinion_pitch_diameter_mm": 480.0, "gear_pitch_diameter_mm": 720.0, "center_distance_mm": 600.0, "output_speed_rpm": 800.0, "ideal_output_torque_Nm": 6.0}),
    ],
)
def test_reference_cases_through_api_and_persisted_json(tmp_path, monkeypatch, edit, expected):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "data" / "project.json")
    client = TestClient(app)
    original = client.get("/api/v1/project").json()
    result = client.patch("/api/v1/project", json=edit)
    assert result.status_code == 200
    payload = result.json()
    assert payload["revision"] == original["revision"] + 1
    for field, reference in expected.items():
        assert payload["derived"][field] == pytest.approx(reference, rel=0, abs=1e-10)
    persisted_json = json.loads(store.STATE_FILE.read_text(encoding="utf-8"))
    assert persisted_json["revision"] == payload["revision"]
    assert persisted_json["requirements"]["input_speed_rpm"] == edit["input_speed_rpm"]
    assert client.get("/api/v1/project").json()["derived"] == payload["derived"]
