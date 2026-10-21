import json
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
import pytest

from aeropkmech import store
from aeropkmech.artifacts import list_artifacts, publish
from aeropkmech.automotive import (
    VehicleGenerationRequest, export_vehicle_component_stl, export_vehicle_drawing_pdf,
    make_vehicle_design, vehicle_bom, vehicle_calculate, vehicle_component_solids, vehicle_manifest,
)
from aeropkmech.families import IMPLEMENTED_FAMILIES, get_family
from aeropkmech.main import app


PROMPT = "Generate a two-seater sports car, electric powered, 4.2 m long, 1.8 m wide, with a 300 km range. Include the necessary mechanical and electrical systems."


def test_prompt_preserves_user_evidence_and_assumed_geometry_defaults():
    from aeropkmech.intelligence import propose_specification
    proposal = propose_specification(PROMPT)
    assert proposal.intent == "SUPPORTED_ELECTRIC_VEHICLE"
    assert proposal.can_commit is True
    parameters = {item.name:item for item in proposal.parameters}
    assert parameters["overall_length_mm"].value == 4200
    assert parameters["overall_length_mm"].unit == "mm"
    assert parameters["overall_length_mm"].source == "user-provided"
    assert parameters["overall_length_mm"].evidence == "4.2 m long"
    assert parameters["target_range_km"].value == 300
    assert parameters["target_range_km"].source == "user-provided"
    assert parameters["wheelbase_mm"].source == "assumed"
    assert any("wheelbase" in question.lower() for question in proposal.unresolved_questions)
    assert proposal.family_id == "electric_vehicle"
    assert "layout drawing PDF" in proposal.supported_artifacts


def test_vehicle_cad_components_have_distinct_valid_solids_and_expected_placement():
    request=VehicleGenerationRequest(expected_revision=1,overall_length_mm=4200,overall_width_mm=1800,occupant_capacity=2,target_range_km=300,body_height_mm=1400,wheelbase_mm=2520,front_track_mm=1500,rear_track_mm=1480,tire_outer_diameter_mm=650,tire_width_mm=225,ground_clearance_mm=150,frame_rail_width_mm=60,frame_rail_height_mm=80,body_width_mm=1200,body_length_mm=4200,provenance={"overall_length_mm":"USER_PROVIDED","overall_width_mm":"USER_PROVIDED","target_range_km":"USER_PROVIDED","occupant_capacity":"USER_PROVIDED"},evidence={"overall_length_mm":"4.2 m long"})
    design=make_vehicle_design(request,2,[])
    solids=vehicle_component_solids(design)
    assert len(solids)==27
    assert all(solid.val().isValid() and solid.val().Volume()>0 for solid in solids.values())
    manifest=vehicle_manifest(design)
    assert len(manifest["components"])==len(solids)
    assert len({tuple(item["dimensions"].values()) for item in manifest["components"]})>5
    calc=vehicle_calculate(design)
    wheel={item["id"]:(item["x_mm"],item["y_mm"],item["z_mm"]) for item in calc["wheel_centers"]}
    assert wheel["front-left"]==(1260,750,325)
    assert wheel["rear-right"]==(-1260,-740,325)
    assert calc["calculation_status"]["range"]=="UNRESOLVED"
    assert calc["calculation_status"]["safety"]=="UNSUPPORTED"
    assert vehicle_bom(design)["items"][0]["material"] is None


def test_default_vehicle_envelope_matches_prompt_and_keeps_tires_visible():
    design = get_family("electric_vehicle", "1.0").default_design()
    calculated = vehicle_calculate(design)
    assert calculated["calculation_status"]["dimensional_consistency"] == "CALCULATED"
    assert calculated["geometry_bounds_mm"]["length"] == pytest.approx(4200, abs=0.1)
    assert calculated["geometry_bounds_mm"]["width"] == pytest.approx(1800, abs=0.1)
    p = design.requirements
    assert p.body_width_mm.value < min(p.front_track_mm.value, p.rear_track_mm.value) - p.tire_width_mm.value


def test_vehicle_mesh_drawing_and_bom_are_real_revision_bound_artifacts(tmp_path):
    request=VehicleGenerationRequest(expected_revision=1,overall_length_mm=4200,overall_width_mm=1800,occupant_capacity=2,target_range_km=300,body_height_mm=1400,wheelbase_mm=2520,front_track_mm=1500,rear_track_mm=1500,tire_outer_diameter_mm=650,tire_width_mm=225,ground_clearance_mm=150,frame_rail_width_mm=60,frame_rail_height_mm=80,body_width_mm=1200,body_length_mm=4200,provenance={"overall_length_mm":"USER_PROVIDED","overall_width_mm":"USER_PROVIDED","target_range_km":"USER_PROVIDED"},evidence={"overall_length_mm":"4.2 m long"})
    design=make_vehicle_design(request,3,[])
    mesh=tmp_path/"body.stl"; export_vehicle_component_stl(design,"body-envelope",mesh)
    raw=mesh.read_bytes(); assert raw[84:88] != b"\0\0\0\0"; assert len(raw)>84
    drawing=tmp_path/"layout.pdf"; export_vehicle_drawing_pdf(design,drawing)
    assert drawing.read_bytes().startswith(b"%PDF")
    assert vehicle_manifest(design)["revision"]==3
    assert vehicle_bom(design)["revision"]==3


def test_vehicle_shared_project_revision_artifacts_and_conflicts(tmp_path,monkeypatch):
    monkeypatch.setattr(store,"DATA_DIR",tmp_path/"data")
    monkeypatch.setattr(store,"STATE_FILE",tmp_path/"data"/"project.json")
    monkeypatch.setattr("aeropkmech.main.ARTIFACTS",tmp_path/"artifacts")
    client=TestClient(app)
    before=client.get("/api/v1/project").json()
    proposal=client.post("/api/v1/specifications/propose",json={"text":PROMPT}).json()
    body={item["name"]:item["value"] for item in proposal["parameters"] if item["name"] not in {"propulsion_type","propulsion_layout"}}
    body.update(expected_revision=before["revision"],propulsion_layout="rear_motor_rear_drive")
    body["provenance"]={item["name"]: ("USER_PROVIDED" if item["source"]=="user-provided" else "ASSUMED") for item in proposal["parameters"] if item["name"] not in {"occupant_capacity","propulsion_type","propulsion_layout"}}
    body["provenance"].update(occupant_capacity="USER_PROVIDED",propulsion_type="USER_PROVIDED")
    body["evidence"]={item["name"]:item["evidence"] for item in proposal["parameters"] if item["evidence"]}
    committed=client.post("/api/v1/project/vehicle/generate",json=body)
    assert committed.status_code==200,committed.text
    project=committed.json(); assert project["revision"]==before["revision"]+1
    assert project["family"]=="electric_vehicle"
    assert project["requirements"]["overall_length_mm"]["source"]=="USER_PROVIDED"
    assert len(project["derived"]["components"])==27
    assert client.get("/api/v1/project").json()["id"]==project["id"]
    mesh=client.get(f"/api/v1/geometry/tire-front-left.stl?revision={project['revision']}")
    assert mesh.status_code==200 and mesh.headers["x-geometry-component-id"]=="tire-front-left"
    assert mesh.headers["x-generator-version"]=="cq-ev-envelope-0.2"
    for path,signature in (("/api/v1/export/step",b"ISO-10303-21;"),("/api/v1/export/stl",None),("/api/v1/vehicle/layout.pdf",b"%PDF"),("/api/v1/vehicle/manifest.json",b"{"),("/api/v1/vehicle/bom.json",b"{")):
        artifact=client.get(path)
        assert artifact.status_code==200, (path,artifact.text[:300])
        assert artifact.headers["x-design-revision"]==str(project["revision"])
        assert artifact.headers["x-artifact-sha256"]
        if signature: assert artifact.content.startswith(signature)
    listing=client.get("/api/v1/artifacts").json()
    assert all(item["revision"]==project["revision"] and not item["stale"] for item in listing["artifacts"])
    assert all(item["dependencies"] for item in listing["artifacts"])
    regenerated=client.post("/api/v1/project/vehicle/generate",json={**body,"expected_revision":project["revision"],"body_height_mm":1410})
    assert regenerated.status_code==200
    stale=client.get("/api/v1/artifacts").json()
    assert stale["current_revision"]==project["revision"]+1
    assert all(item["stale"] for item in stale["artifacts"])
    old_filename=next(item["filename"] for item in stale["artifacts"] if item["kind"]=="manifest")
    assert client.get(f"/api/v1/artifacts/{old_filename}").headers["x-artifact-stale"]=="true"
    conflict=client.post("/api/v1/project/vehicle/generate",json={**body,"expected_revision":before["revision"]})
    assert conflict.status_code==409
    assert client.patch("/api/v1/project",json={"gear_teeth":60}).status_code==422
    assert IMPLEMENTED_FAMILIES["electric_vehicle"].metadata.schema_version=="1.0"


def test_vehicle_component_generation_failure_does_not_suppress_partner_mesh(tmp_path,monkeypatch):
    monkeypatch.setattr(store,"DATA_DIR",tmp_path/"data");monkeypatch.setattr(store,"STATE_FILE",tmp_path/"data"/"project.json")
    monkeypatch.setattr("aeropkmech.main.ARTIFACTS",tmp_path/"artifacts")
    client=TestClient(app)
    initialized=client.post("/api/v1/project/initialize",json={"family_id":"electric_vehicle"}).json()
    from aeropkmech import main
    original=main.export_vehicle_component_stl
    def fail_one(design,component_id,target):
        if component_id=="tire-front-left": raise RuntimeError("injected component failure")
        return original(design,component_id,target)
    monkeypatch.setattr(main,"export_vehicle_component_stl",fail_one)
    failed=client.get(f"/api/v1/geometry/tire-front-left.stl?revision={initialized['revision']}")
    partner=client.get(f"/api/v1/geometry/tire-front-right.stl?revision={initialized['revision']}")
    assert failed.status_code==500 and "injected component failure" in failed.json()["detail"]
    assert partner.status_code==200
    indexed=client.get("/api/v1/artifacts").json()["artifacts"]
    assert [item["kind"] for item in indexed]==["tire-front-right"]


def test_concurrent_component_artifact_publication_keeps_complete_index(tmp_path):
    design = get_family("electric_vehicle", "1.0").default_design()
    directory = tmp_path / "artifacts"
    def publish_one(index):
        return publish(f"mesh-{index}".encode(), directory, design, f"component-{index}", "stl", "cad-test-1")[1]
    with ThreadPoolExecutor(max_workers=8) as workers:
        published = list(workers.map(publish_one, range(27)))
    indexed = list_artifacts(directory, design)
    assert len(indexed) == 27
    assert {item["artifact_id"] for item in indexed} == {item["artifact_id"] for item in published}
    assert all(item["available"] and not item["stale"] for item in indexed)
