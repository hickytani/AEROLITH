from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from aeropkmech import store
from aeropkmech.automotive import propagate_vehicle_edits, vehicle_component_solids
from aeropkmech.families import get_family
from aeropkmech.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "data" / "project.json")
    monkeypatch.setattr("aeropkmech.main.ARTIFACTS", tmp_path / "artifacts")
    return TestClient(app)


def init_vehicle(client):
    return client.post("/api/v1/project/initialize", json={"family_id": "electric_vehicle"}).json()


def test_vehicle_edit_regenerates_dependent_geometry_and_records_revision_and_evidence(client):
    initial = init_vehicle(client)
    initial_cad = vehicle_component_solids(store.load())
    response = client.patch("/api/v1/project/vehicle", json={
        "expected_revision": initial["revision"], "wheelbase_mm": 2700,
    })
    assert response.status_code == 200, response.text
    changed = response.json()
    assert changed["revision"] == initial["revision"] + 1
    assert changed["history"][-1]["revision"] == initial["revision"]
    assert changed["requirements"]["wheelbase_mm"]["value"] == 2700
    assert changed["requirements"]["wheelbase_mm"]["source"] == "USER_PROVIDED"
    assert changed["edit_result"]["regenerated_components"] and len(changed["edit_result"]["regenerated_components"]) == 27
    assert changed["verification"]["wheel_axle_placement"]["state"] == "PASSED"
    assert changed["verification"]["frame_dimensions"]["state"] == "PASSED"
    assert changed["verification"]["mechanical_interfaces"]["state"] == "PARTIAL"
    assert changed["derived"]["wheel_centers"][0]["x_mm"] == 1350
    new_cad = vehicle_component_solids(store.load())
    assert set(initial_cad) == set(new_cad)
    assert initial_cad["front-axle-reference"].val().BoundingBox().xmin != pytest.approx(new_cad["front-axle-reference"].val().BoundingBox().xmin)
    assert initial_cad["body-envelope"].val().Volume() == pytest.approx(new_cad["body-envelope"].val().Volume())


def test_overall_dimensions_propagate_only_to_documented_assumed_dependents(client):
    initial = init_vehicle(client)
    response = client.patch("/api/v1/project/vehicle", json={
        "expected_revision": initial["revision"], "overall_length_mm": 4400, "overall_width_mm": 1900,
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["requirements"]["body_length_mm"]["value"] == 4400
    assert result["requirements"]["wheelbase_mm"]["value"] == pytest.approx(2640)
    assert result["requirements"]["front_track_mm"]["value"] == pytest.approx(1675)
    assert result["derived"]["geometry_bounds_mm"]["length"] == pytest.approx(4400)
    assert result["derived"]["geometry_bounds_mm"]["width"] == pytest.approx(1900)
    assert result["verification"]["overall_envelope_containment"]["state"] == "PASSED"
    assert "body_length_mm" in result["edit_result"]["propagated_parameters"]["overall_length_mm"]
    assert "front_track_mm (assumed value scaled proportionally)" in result["edit_result"]["propagated_parameters"]["overall_width_mm"]


def test_matching_explicit_body_length_keeps_user_provenance_when_overall_length_changes(client):
    initial=init_vehicle(client)
    response=client.patch("/api/v1/project/vehicle",json={
        "expected_revision":initial["revision"],"overall_length_mm":4300,"body_length_mm":4300,
    })
    assert response.status_code==200,response.text
    values=response.json()["requirements"]
    assert values["body_length_mm"]["source"]=="USER_PROVIDED"
    assert values["body_length_mm"]["value"]==4300


@pytest.mark.parametrize("body", [
    {"expected_revision": 1, "unknown_dimension_mm": 800},
    {"expected_revision": 1, "wheelbase_mm": 9000},
    {"expected_revision": 1, "wheelbase_mm": "NaN"},
    {"expected_revision": 1, "wheelbase_mm": 1001, "overall_length_mm": 1600},
])
def test_invalid_or_unknown_vehicle_edits_preserve_canonical_state(client, body):
    initial = init_vehicle(client)
    body["expected_revision"] = initial["revision"]
    before = deepcopy(client.get("/api/v1/project").json())
    response = client.patch("/api/v1/project/vehicle", json=body)
    assert response.status_code == 422
    assert client.get("/api/v1/project").json() == before


def test_stale_vehicle_edit_returns_conflict_and_current_revision(client):
    initial = init_vehicle(client)
    changed = client.patch("/api/v1/project/vehicle", json={"expected_revision": initial["revision"], "wheelbase_mm": 2700})
    assert changed.status_code == 200
    stale = client.patch("/api/v1/project/vehicle", json={"expected_revision": initial["revision"], "wheelbase_mm": 2600})
    assert stale.status_code == 409
    assert stale.headers["x-design-revision"] == str(initial["revision"] + 1)
    assert client.get("/api/v1/project").json()["requirements"]["wheelbase_mm"]["value"] == 2700


def test_vehicle_edit_requires_revision_and_nonempty_geometry_changes(client):
    initial=init_vehicle(client)
    for body in ({"wheelbase_mm":2700},{"expected_revision":initial["revision"]}):
        rejected=client.patch("/api/v1/project/vehicle",json=body)
        assert rejected.status_code==422
    assert client.get("/api/v1/project").json()["revision"]==initial["revision"]


def test_geometry_failure_during_candidate_regeneration_does_not_commit(client, monkeypatch):
    initial = init_vehicle(client)
    before = client.get("/api/v1/project").json()
    def fail(_design):
        raise RuntimeError("injected Open CASCADE regeneration failure")
    monkeypatch.setattr("aeropkmech.main.vehicle_component_solids", fail)
    response = client.patch("/api/v1/project/vehicle", json={"expected_revision": initial["revision"], "wheelbase_mm": 2700})
    assert response.status_code == 500
    assert response.headers["x-verification-state"] == "EXECUTION_ERROR"
    assert "Open CASCADE" not in response.text
    assert client.get("/api/v1/project").json() == before


def test_revision_is_rechecked_after_candidate_cad_generation(client,monkeypatch):
    import aeropkmech.main as main
    initial=init_vehicle(client)
    original=main.vehicle_verification
    def concurrent_write(candidate):
        latest=store.load()
        latest.revision+=1
        latest.requirements.wheelbase_mm.value=2600
        store.save(latest)
        return original(candidate)
    monkeypatch.setattr(main,"vehicle_verification",concurrent_write)
    response=client.patch("/api/v1/project/vehicle",json={"expected_revision":initial["revision"],"wheelbase_mm":2700})
    assert response.status_code==409
    assert response.headers["x-design-revision"]==str(initial["revision"]+1)
    latest=client.get("/api/v1/project").json()
    assert latest["revision"]==initial["revision"]+1
    assert latest["requirements"]["wheelbase_mm"]["value"]==2600


def test_vehicle_artifacts_are_current_then_stale_after_edit(client):
    initial = init_vehicle(client)
    artifact = client.get("/api/v1/vehicle/manifest.json")
    assert artifact.status_code == 200
    assert artifact.headers["x-generator-version"] == "cq-ev-envelope-0.2"
    dependencies=client.get("/api/v1/artifacts").json()["artifacts"][0]["dependencies"]
    assert any(item["key"]=="vehicle_parameter:wheelbase_mm" for item in dependencies)
    updated = client.patch("/api/v1/project/vehicle", json={"expected_revision": initial["revision"], "tire_width_mm": 230})
    assert updated.status_code == 200, updated.text
    assert updated.json()["edit_result"]["artifacts_regenerated"] == []
    assert len(updated.json()["edit_result"]["artifacts_stale"]) == 1
    listing = client.get("/api/v1/artifacts").json()
    assert listing["artifacts"][0]["stale"] is True
    new_manifest = client.get("/api/v1/vehicle/manifest.json")
    assert new_manifest.headers["x-design-revision"] == str(initial["revision"] + 1)
    assert new_manifest.headers["x-generator-version"] == "cq-ev-envelope-0.2"


def test_equivalent_inputs_generate_equivalent_cad_and_step_reopens(client,tmp_path):
    import cadquery as cq
    initial=init_vehicle(client)
    first=vehicle_component_solids(store.load())
    equivalent=store.load().model_copy(deep=True)
    equivalent.revision+=1
    equivalent.updated_at="later-revision"
    repeated=vehicle_component_solids(equivalent)
    assert set(first)==set(repeated)
    for component_id in first:
        a=first[component_id].val();b=repeated[component_id].val()
        assert a.Volume()==pytest.approx(b.Volume(),rel=1e-10)
        assert a.BoundingBox().xlen==pytest.approx(b.BoundingBox().xlen,abs=1e-9)
    step=client.get("/api/v1/export/step")
    assert step.status_code==200
    path=tmp_path/"vehicle.step";path.write_bytes(step.content)
    reopened=cq.importers.importStep(str(path))
    solids=reopened.solids().vals()
    assert len(solids)==27
    assert all(item.isValid() and item.Volume()>0 for item in solids)
    assert step.headers["x-design-revision"]==str(initial["revision"])
    assert step.headers["x-generator-version"]=="cq-ev-envelope-0.2"


@pytest.mark.parametrize("parameter,value,component_id",[
    ("overall_length_mm",4300,"body-envelope"),
    ("overall_width_mm",1900,"tire-front-left"),
    ("body_height_mm",1450,"body-envelope"),
    ("wheelbase_mm",2700,"frame-rail-left"),
    ("front_track_mm",1550,"tire-front-left"),
    ("rear_track_mm",1550,"rear-axle-reference"),
    ("tire_outer_diameter_mm",700,"tire-front-left"),
    ("tire_width_mm",230,"tire-front-left"),
    ("ground_clearance_mm",160,"frame-rail-left"),
    ("frame_rail_width_mm",70,"frame-rail-left"),
    ("frame_rail_height_mm",90,"frame-rail-left"),
    ("body_width_mm",1300,"body-envelope"),
    ("body_length_mm",4100,"body-envelope"),
])
def test_each_exposed_vehicle_parameter_changes_its_dependent_cad(parameter,value,component_id):
    design=get_family("electric_vehicle").default_design()
    before=vehicle_component_solids(design)[component_id].val()
    candidate,_=propagate_vehicle_edits(design,{parameter:value})
    after=vehicle_component_solids(candidate)[component_id].val()
    def signature(shape):
        bounds=shape.BoundingBox()
        return (shape.Volume(),bounds.xmin,bounds.xmax,bounds.ymin,bounds.ymax,bounds.zmin,bounds.zmax)
    assert signature(before)!=pytest.approx(signature(after),abs=1e-6),parameter

