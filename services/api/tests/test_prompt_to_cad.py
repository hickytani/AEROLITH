"""End-to-end prompts must update canonical values and real CAD geometry."""
import hashlib

from fastapi.testclient import TestClient

from aeropkmech import store
from aeropkmech.main import app


EV_PROMPT = (
    "Generate a two-seater sports car, electric powered, 4.2 m long, "
    "1.8 m wide, with a 300 km range. Include the necessary mechanical and electrical systems."
)
GEAR_PROMPT = (
    "Design an external spur gear pair with pinion 20 teeth, driven gear 60 teeth, "
    "module 2 mm, face width 12 mm, input torque 8 Nm, and input speed 900 rpm."
)


def _use_temp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "data" / "project.json")
    monkeypatch.setattr("aeropkmech.main.ARTIFACTS", tmp_path / "artifacts")
    return TestClient(app)


def test_gear_prompt_review_acceptance_regenerates_real_revision_bound_cad(tmp_path, monkeypatch):
    client = _use_temp_store(tmp_path, monkeypatch)
    initial = client.get("/api/v1/project").json()
    before_mesh = client.get(f"/api/v1/geometry/pinion.stl?revision={initial['revision']}")
    assert before_mesh.status_code == 200

    proposal_response = client.post("/api/v1/specifications/propose", json={"text": GEAR_PROMPT})
    assert proposal_response.status_code == 200
    proposal = proposal_response.json()
    assert proposal["can_commit"] is True
    assert proposal["request"] == GEAR_PROMPT
    assert client.get("/api/v1/project").json() == initial

    values = {item["name"]: item["value"] for item in proposal["parameters"]}
    evidence = {item["name"]: item["evidence"] for item in proposal["parameters"] if item["evidence"]}
    sources = {item["name"]: item["source"] for item in proposal["parameters"]}
    accepted = client.patch("/api/v1/project", json={
        **{name: values[name] for name in ("pinion_teeth", "gear_teeth", "module_mm", "face_width_mm", "input_torque_Nm", "input_speed_rpm")},
        "expected_revision": initial["revision"], "source_prompt": GEAR_PROMPT,
        "requirement_sources": sources, "requirement_evidence": evidence,
    })
    assert accepted.status_code == 200, accepted.text
    project = accepted.json()
    assert project["revision"] == initial["revision"] + 1
    assert project["source_prompt"] == GEAR_PROMPT
    assert project["components"][0]["teeth"] == 20
    assert project["components"][1]["teeth"] == 60
    assert project["derived"]["center_distance_mm"] == 80
    assembly = project["assembly_verification"]
    assert assembly["revision"] == assembly["geometry_revision"] == project["revision"]
    assert assembly["source_prompt_sha256"]
    assert assembly["requirements"]["module_mm"]["source_span"]["text"] == "module 2 mm"
    assert next(check for check in assembly["checks"] if check["id"] == "gear.profile-dimensions")["state"] == "PASSED"
    assert next(check for check in assembly["checks"] if check["id"] == "gear.tooth-contact")["state"] == "UNOBSERVABLE"

    trace = project["requirement_traceability"]
    assert trace["source_prompt"] == GEAR_PROMPT
    assert trace["components"]["pinion"] == ["pinion_teeth", "module_mm", "face_width_mm"]
    module_span = trace["parameters"]["module_mm"]["source_span"]
    assert GEAR_PROMPT[module_span["start"]:module_span["end"]] == "module 2 mm"
    assert project["requirement_traceability"]["parameters"]["pinion_teeth"]["value"] == 20

    after_mesh = client.get(f"/api/v1/geometry/pinion.stl?revision={project['revision']}")
    assert after_mesh.status_code == 200
    assert after_mesh.content != before_mesh.content
    assert after_mesh.headers["x-design-revision"] == str(project["revision"])
    assert after_mesh.headers["x-artifact-sha256"]
    artifacts = client.get("/api/v1/artifacts").json()["artifacts"]
    old_mesh_artifact = next(item for item in artifacts if item["kind"] == "pinion" and item["revision"] == initial["revision"])
    assert old_mesh_artifact["stale"] is True and old_mesh_artifact["available"] is True
    old_download = client.get(f"/api/v1/artifacts/{old_mesh_artifact['filename']}")
    assert old_download.status_code == 200
    assert old_download.headers["x-artifact-stale"] == "true"
    assert hashlib.sha256(old_download.content).hexdigest() == old_mesh_artifact["sha256"]
    step = client.get("/api/v1/export/step")
    assert step.status_code == 200 and step.content.startswith(b"ISO-10303-21;")
    assert step.headers["x-design-revision"] == str(project["revision"])
    assert project["verification"]["polygonal_geometry"]["state"] == "WARNING"


def test_ev_prompt_review_acceptance_regenerates_traceable_concept_assembly(tmp_path, monkeypatch):
    client = _use_temp_store(tmp_path, monkeypatch)
    initial = client.get("/api/v1/project").json()
    proposed = client.post("/api/v1/specifications/propose", json={"text": EV_PROMPT})
    assert proposed.status_code == 200
    proposal = proposed.json()
    assert proposal["can_commit"] is True
    assert proposal["completion_scope"] == "PARTIAL_WITH_UNSUPPORTED_REQUESTS"
    assert proposal["unsupported_requests"]
    assert client.get("/api/v1/project").json() == initial

    values = {item["name"]: item["value"] for item in proposal["parameters"] if item["name"] not in {"propulsion_type", "propulsion_layout"}}
    provenance = {item["name"]: ("USER_PROVIDED" if item["source"] == "user-provided" else "ASSUMED") for item in proposal["parameters"] if item["name"] not in {"propulsion_type", "propulsion_layout"}}
    evidence = {item["name"]: item["evidence"] for item in proposal["parameters"] if item["evidence"]}
    provenance.update({"propulsion_type":"USER_PROVIDED", "propulsion_layout":"ASSUMED"})
    committed_response = client.post("/api/v1/project/vehicle/generate", json={
        **values, "expected_revision": initial["revision"], "provenance": provenance,
        "evidence": evidence, "source_prompt": EV_PROMPT,
    })
    assert committed_response.status_code == 200, committed_response.text
    project = committed_response.json()
    assert project["revision"] == initial["revision"] + 1
    assert project["source_prompt"] == EV_PROMPT
    assert len(project["derived"]["components"]) == 27
    assert project["verification"]["requirement_component_traceability"]["state"] == "PASSED"
    assert project["verification"]["mechanical_interfaces"]["state"] == "PARTIAL"
    assert project["verification"]["range_sizing"]["state"] == "UNKNOWN"
    assembly = project["assembly_verification"]
    assert assembly["revision"] == assembly["geometry_revision"] == project["revision"]
    assert assembly["source_prompt_sha256"] == hashlib.sha256(EV_PROMPT.encode("utf-8")).hexdigest()
    assert next(check for check in assembly["checks"] if check["id"] == "ev.chassis.front-crossmember-rail-joints")["state"] == "PASSED"
    assert next(check for check in assembly["checks"] if check["id"] == "ev.propulsion-frame-interface")["state"] == "UNOBSERVABLE"
    assert all(item["state"] != "MATCH" for item in project["verification"].values())

    manifest_response = client.get("/api/v1/vehicle/manifest.json")
    assert manifest_response.status_code == 200
    manifest = manifest_response.json()
    assert manifest["revision"] == project["revision"]
    assert manifest["source_prompt"] == EV_PROMPT
    assert manifest["source_prompt_sha256"] == hashlib.sha256(EV_PROMPT.encode("utf-8")).hexdigest()
    tire = next(item for item in manifest["components"] if item["id"] == "tire-front-left")
    assert tire["parameter_refs"]
    assert "tire_outer_diameter_mm" in tire["parameter_refs"]
    assert tire["requirement_traceability"]["overall_length_mm"]["source"] == "user-provided"
    assert tire["requirement_traceability"]["tire_outer_diameter_mm"]["source"] == "assumed"
    assert tire["requirement_traceability"]["overall_length_mm"]["source_span"]["text"] == "4.2 m long"

    step = client.get("/api/v1/export/step")
    assert step.status_code == 200 and step.content.startswith(b"ISO-10303-21;")
    assert step.headers["x-design-revision"] == str(project["revision"])
    assert client.get(f"/api/v1/geometry/tire-front-left.stl?revision={project['revision']}").status_code == 200


def test_conflicting_prompt_stays_uncommitted_and_stale_review_is_rejected(tmp_path, monkeypatch):
    client = _use_temp_store(tmp_path, monkeypatch)
    original = client.get("/api/v1/project").json()
    existing_artifact = client.get(f"/api/v1/geometry/pinion.stl?revision={original['revision']}")
    assert existing_artifact.status_code == 200

    conflict = client.post("/api/v1/specifications/propose", json={"text": "External spur gear pair, pinion 18 teeth and pinion 20 teeth, driven gear 54 teeth, module 2 mm, face width 12 mm, torque 8 Nm, speed 900 rpm"}).json()
    assert conflict["can_commit"] is False
    assert conflict["conflicts"]
    assert client.get("/api/v1/project").json() == original
    preserved = client.get("/api/v1/artifacts").json()["artifacts"]
    preserved_entry = next(item for item in preserved if item["sha256"] == existing_artifact.headers["x-artifact-sha256"])
    old_response = client.get(f"/api/v1/artifacts/{preserved_entry['filename']}")
    assert old_response.status_code == 200
    assert old_response.headers["x-artifact-stale"] == "false"
    assert hashlib.sha256(old_response.content).hexdigest() == preserved_entry["sha256"]

    proposal = client.post("/api/v1/specifications/propose", json={"text": GEAR_PROMPT}).json()
    changed = client.patch("/api/v1/project", json={"gear_teeth": 72, "expected_revision": original["revision"]})
    assert changed.status_code == 200
    values = {item["name"]: item["value"] for item in proposal["parameters"]}
    stale_acceptance = client.patch("/api/v1/project", json={
        **{name: values[name] for name in ("pinion_teeth", "gear_teeth", "module_mm", "face_width_mm", "input_torque_Nm", "input_speed_rpm")},
        "expected_revision": original["revision"], "source_prompt": GEAR_PROMPT,
    })
    assert stale_acceptance.status_code == 409
    assert client.get("/api/v1/project").json()["revision"] == original["revision"] + 1
    artifacts = client.get("/api/v1/artifacts").json()["artifacts"]
    assert all(item["stale"] for item in artifacts)
    for item in artifacts:
        download = client.get(f"/api/v1/artifacts/{item['filename']}")
        assert download.status_code == 200
        assert download.headers["x-artifact-stale"] == "true"
        assert hashlib.sha256(download.content).hexdigest() == item["sha256"]


def test_fabricated_requirement_evidence_is_rejected_without_state_mutation(tmp_path, monkeypatch):
    client = _use_temp_store(tmp_path, monkeypatch)
    original = client.get("/api/v1/project").json()
    response = client.patch("/api/v1/project", json={
        "module_mm": 2.5,
        "expected_revision": original["revision"],
        "source_prompt": GEAR_PROMPT,
        "requirement_sources": {"module_mm": "user-provided"},
        "requirement_evidence": {"module_mm": "module 2.5 mm"},
    })
    assert response.status_code == 422
    assert client.get("/api/v1/project").json() == original
