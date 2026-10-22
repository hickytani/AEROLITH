"""Browser-independent workflow acceptance against a real Uvicorn HTTP process.

Run with: uv run --cache-dir .uv-cache pytest services/api/tests/test_http_acceptance.py -q
All project and artifact data is scoped to pytest's disposable temporary directory.
"""
from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[3]
GEAR_PROMPT = (
    "Design an external spur gear pair with pinion 20 teeth, driven gear 60 teeth, "
    "module 2 mm, pressure angle 25 degrees, face width 12 mm, input torque 8 Nm, "
    "and input speed 900 rpm."
)
EV_PROMPT = (
    "Generate a two-seater sports car, electric powered, 4.2 m long, "
    "1.8 m wide, with a 300 km range. Include the necessary mechanical and electrical systems."
)


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _start_api(tmp_path: Path):
    port = _available_port()
    data_dir = tmp_path / "isolated-data"
    artifacts_dir = tmp_path / "isolated-artifacts"
    data_dir.mkdir()
    artifacts_dir.mkdir()
    log_path = tmp_path / "uvicorn.log"
    log = log_path.open("w+b")
    env = os.environ.copy()
    env["AEROPKMECH_DATA_DIR"] = str(data_dir)
    env["AEROPKMECH_ARTIFACTS_DIR"] = str(artifacts_dir)
    # Keep the spawned CAD/API worker predictable on memory-constrained hosts.
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["OMP_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"
    env["NUMEXPR_NUM_THREADS"] = "1"
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "aeropkmech.main:app", "--app-dir", str(ROOT / "services" / "api"),
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"
    client = httpx.Client(base_url=base_url, timeout=120)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        try:
            if client.get("/api/v1/health", timeout=2).status_code == 200:
                return process, client, log, log_path
        except httpx.HTTPError:
            time.sleep(0.25)
    client.close()
    process.terminate()
    process.wait(timeout=10)
    log.close()
    detail = log_path.read_text(encoding="utf-8", errors="replace")
    raise AssertionError(f"Isolated Uvicorn API failed to become ready. Server output:\n{detail}")


def _json(response: httpx.Response):
    assert response.is_success, f"HTTP {response.status_code}: {response.text[:1000]}"
    return response.json()


def _artifact(client: httpx.Client, kind: str, revision: int, project_id: str):
    entries = _json(client.get("/api/v1/artifacts"))["artifacts"]
    item = next(item for item in entries if item["kind"] == kind and item["revision"] == revision)
    assert item["project_id"] == project_id
    return item


def _assert_artifact_response(response: httpx.Response, revision: int):
    assert response.status_code == 200
    assert response.headers["x-design-revision"] == str(revision)
    assert hashlib.sha256(response.content).hexdigest() == response.headers["x-artifact-sha256"]


def _verify_download(client: httpx.Client, item: dict, stale: bool):
    response = client.get(f"/api/v1/artifacts/{item['filename']}")
    assert response.status_code == 200
    assert response.headers["x-artifact-stale"] == str(stale).lower()
    assert hashlib.sha256(response.content).hexdigest() == item["sha256"]
    return response.content


def test_real_http_gear_and_conceptual_ev_workflows(tmp_path):
    process, client, log, log_path = _start_api(tmp_path)
    try:
        initial = _json(client.get("/api/v1/project"))
        project_id = initial["id"]
        assert initial["revision"] == 1

        proposal = _json(client.post("/api/v1/specifications/propose", json={"text": GEAR_PROMPT}))
        assert proposal["can_commit"] is True
        assert proposal["request"] == GEAR_PROMPT
        by_name = {item["name"]: item for item in proposal["parameters"]}
        assert by_name["pressure_angle_deg"]["evidence"] == "pressure angle 25 degrees"
        assert by_name["module_mm"]["source"] == "user-provided"
        assert proposal["conflicts"] == []
        assert proposal["unresolved_questions"] == []
        assert by_name["module_mm"]["quantity"]["value"] == 2
        assert by_name["module_mm"]["quantity"]["canonical_unit"] == "mm"
        assert by_name["module_mm"]["quantity"]["input_value"] == 2
        assert by_name["module_mm"]["quantity"]["input_unit"] == "mm"
        assert client.get("/api/v1/project").json() == initial  # Proposals cannot mutate state.

        values = {name: by_name[name]["value"] for name in (
            "pinion_teeth", "gear_teeth", "module_mm", "pressure_angle_deg", "face_width_mm",
            "input_torque_Nm", "input_speed_rpm",
        )}
        evidence = {name: item["evidence"] for name, item in by_name.items() if item.get("evidence")}
        sources = {name: item["source"] for name, item in by_name.items()}
        committed = _json(client.patch("/api/v1/project", json={
            **values, "expected_revision": initial["revision"], "source_prompt": GEAR_PROMPT,
            "requirement_sources": sources, "requirement_evidence": evidence,
        }))
        gear_revision = committed["revision"]
        assert committed["id"] == project_id and gear_revision == 2
        assert committed["requirements"]["pressure_angle_deg"] == 25
        assert committed["requirement_traceability"]["parameters"]["module_mm"]["value"] == 2
        gear_module_record = committed["parameter_records"]["module_mm"]
        assert gear_module_record["project_id"] == project_id
        assert gear_module_record["family_id"] == "spur_gear_pair"
        assert gear_module_record["revision"] == gear_revision
        assert gear_module_record["quantity"]["value"] == 2
        assert committed["assembly_verification"]["revision"] == gear_revision
        checks = {item["id"]: item["state"] for item in committed["assembly_verification"]["checks"]}
        assert checks["gear.profile-dimensions"] == "PASSED"
        assert checks["gear.base-circles"] == "PASSED"

        pinion = client.get(f"/api/v1/geometry/pinion.stl?revision={gear_revision}")
        assert pinion.status_code == 200
        assert pinion.headers["x-design-revision"] == str(gear_revision)
        assert pinion.headers["x-geometry-component-id"] == "pinion"
        assert hashlib.sha256(pinion.content).hexdigest() == pinion.headers["x-artifact-sha256"]
        step = client.get("/api/v1/export/step")
        _assert_artifact_response(step, gear_revision)
        assert step.content.startswith(b"ISO-10303-21;")
        for path in ("/api/v1/export/stl", "/api/v1/gear/layout.pdf", "/api/v1/report.pdf"):
            _assert_artifact_response(client.get(path), gear_revision)
        for kind in ("assembly", "gear-reference-drawing"):
            assert _artifact(client, kind, gear_revision, project_id)["stale"] is False
        gear_artifacts = _json(client.get("/api/v1/artifacts"))["artifacts"]
        assert any(item["kind"] == "report" and item["filename"].endswith(".pdf")
                   and item["revision"] == gear_revision and item["project_id"] == project_id for item in gear_artifacts)
        old_gear_mesh = _artifact(client, "pinion", gear_revision, project_id)
        _verify_download(client, old_gear_mesh, stale=False)

        rejected = client.patch("/api/v1/project", json={"gear_teeth": 500, "expected_revision": gear_revision})
        assert rejected.status_code == 422
        assert client.get("/api/v1/project").json()["revision"] == gear_revision
        _verify_download(client, old_gear_mesh, stale=False)

        changed = _json(client.patch("/api/v1/project", json={"module_mm": 2.5, "expected_revision": gear_revision}))
        changed_revision = changed["revision"]
        assert changed_revision == gear_revision + 1
        stale_gear_mesh = _artifact(client, "pinion", gear_revision, project_id)
        assert stale_gear_mesh["stale"] is True and stale_gear_mesh["available"] is True
        _verify_download(client, stale_gear_mesh, stale=True)
        new_mesh = client.get(f"/api/v1/geometry/pinion.stl?revision={changed_revision}")
        _assert_artifact_response(new_mesh, changed_revision)
        assert new_mesh.content != pinion.content
        new_step = client.get("/api/v1/export/step")
        _assert_artifact_response(new_step, changed_revision)

        ev_proposal = _json(client.post("/api/v1/specifications/propose", json={"text": EV_PROMPT}))
        assert ev_proposal["can_commit"] is True
        proposed_length = next(item for item in ev_proposal["parameters"] if item["name"] == "overall_length_mm")
        assert proposed_length["evidence"] == "4.2 m long"
        assert proposed_length["quantity"]["input_value"] == 4.2
        assert proposed_length["quantity"]["input_unit"] == "m"
        assert proposed_length["quantity"]["conversion_factor"] == 1000
        assert proposed_length["quantity"]["value"] == 4200
        assert proposed_length["quantity"]["canonical_unit"] == "mm"
        ev_values = {item["name"]: item["value"] for item in ev_proposal["parameters"]
                     if item["name"] not in {"propulsion_type", "propulsion_layout"}}
        ev_evidence = {item["name"]: item["evidence"] for item in ev_proposal["parameters"] if item.get("evidence")}
        provenance = {item["name"]: ("USER_PROVIDED" if item["source"] == "user-provided" else "ASSUMED")
                      for item in ev_proposal["parameters"] if item["name"] not in {"propulsion_type", "propulsion_layout"}}
        provenance.update({"propulsion_type": "USER_PROVIDED", "propulsion_layout": "ASSUMED"})
        ev = _json(client.post("/api/v1/project/vehicle/generate", json={
            **ev_values, "expected_revision": changed_revision, "provenance": provenance,
            "evidence": ev_evidence, "source_prompt": EV_PROMPT,
        }))
        ev_revision = ev["revision"]
        assert ev["id"] == project_id and ev_revision == changed_revision + 1
        assert ev["derived"]["overall_length_mm"] == 4200
        ev_length_record = ev["parameter_records"]["overall_length_mm"]
        assert ev_length_record["project_id"] == project_id
        assert ev_length_record["family_id"] == "electric_vehicle"
        assert ev_length_record["revision"] == ev_revision
        assert ev_length_record["quantity"]["input_value"] == 4.2
        assert ev_length_record["quantity"]["input_unit"] == "m"
        assert ev["verification"]["mechanical_interfaces"]["state"] == "PARTIAL"
        assert ev["verification"]["range_sizing"]["state"] == "UNKNOWN"
        manifest = _json(client.get("/api/v1/vehicle/manifest.json"))
        assert manifest["revision"] == ev_revision
        assert manifest["design_status"] == "CONCEPTUAL_GEOMETRY"
        tire = client.get(f"/api/v1/geometry/tire-front-left.stl?revision={ev_revision}")
        _assert_artifact_response(tire, ev_revision)
        assert manifest["design_id"] == project_id
        for path in ("/api/v1/export/step", "/api/v1/export/stl", "/api/v1/vehicle/layout.pdf"):
            _assert_artifact_response(client.get(path), ev_revision)
        bom_response = client.get("/api/v1/vehicle/bom.json")
        _assert_artifact_response(bom_response, ev_revision)
        bom = bom_response.json()
        assert bom["design_id"] == project_id and bom["revision"] == ev_revision
        assert all(item["material"] is None and item["mass_kg"] is None and item["cost"] is None for item in bom["items"])
        for kind in ("assembly", "layout-drawing", "manifest", "bom"):
            assert _artifact(client, kind, ev_revision, project_id)["stale"] is False
        old_ev_height = ev["editable_parameters"]["body_height_mm"]["value"]
        old_ev_manifest = _artifact(client, "manifest", ev_revision, project_id)
        assert old_ev_manifest["stale"] is False and old_ev_manifest["available"] is True

        edited_ev = _json(client.post("/api/v1/project/vehicle/generate", json={
            **ev_values, "expected_revision": ev_revision, "provenance": provenance, "evidence": ev_evidence,
            "source_prompt": EV_PROMPT, "body_height_mm": old_ev_height + 10,
        }))
        assert edited_ev["revision"] == ev_revision + 1 and edited_ev["id"] == project_id
        stale_manifest = _artifact(client, "manifest", ev_revision, project_id)
        assert stale_manifest["stale"] is True and stale_manifest["available"] is True
        _verify_download(client, stale_manifest, stale=True)
    finally:
        client.close()
        unexpectedly_exited = process.poll() is not None
        if not unexpectedly_exited:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        log.close()
        if unexpectedly_exited and process.returncode != 0:
            output = log_path.read_text(encoding="utf-8", errors="replace")
            raise AssertionError(f"Uvicorn exited unexpectedly ({process.returncode}). Output:\n{output}")
