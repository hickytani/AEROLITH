"""Typed assembly checks must be tied to actual generated CAD and revision."""
import copy

import cadquery as cq
import pytest
from fastapi.testclient import TestClient

from aeropkmech import cad, store
from aeropkmech.assemblies import AssemblyEvidence, build_assembly_evidence, _ev_assembly
from aeropkmech.automotive import vehicle_component_solids
from aeropkmech.families import get_family
from aeropkmech.main import app


def test_gear_assembly_inspects_real_solids_transform_and_revision():
    design = get_family("spur_gear_pair").default_design()
    evidence = AssemblyEvidence.model_validate(build_assembly_evidence(design))
    assert evidence.assembly_id == "gear-pair"
    assert evidence.revision == evidence.geometry_revision == design.revision
    assert {item.id for item in evidence.components} == {"pinion", "gear"}
    assert all(item.geometry_valid and item.volume_mm3 > 0 for item in evidence.components)
    center = next(item for item in evidence.checks if item.id == "gear.center-distance")
    assert center.state == "PASSED"
    assert center.expected["distance_mm"] == pytest.approx(center.observed["distance_mm"], abs=0.05)
    assert center.geometry_revision == design.revision
    ratio = next(item for item in evidence.checks if item.id == "gear.ratio-derivation")
    assert ratio.state == "PARTIAL"
    assert ratio.observed["source"] == "gear_teeth / pinion_teeth"
    contact = next(item for item in evidence.checks if item.id == "gear.tooth-contact")
    assert contact.state == "UNOBSERVABLE"
    assert evidence.overall_state == "PARTIAL"


def test_gear_relationship_violation_in_generated_assembly_is_detected(monkeypatch):
    design = get_family("spur_gear_pair").default_design()
    real = cad.build_assembly(design)
    moved = cq.Assembly(name="deliberately-moved-gear")
    for child in real.children:
        translation, rotation = child.loc.toTuple()
        if child.name == "driven_gear":
            translation = (translation[0] + 10, translation[1], translation[2])
        moved.add(child.obj, name=child.name, loc=cq.Location(cq.Vector(*translation), cq.Vector(0, 0, 1), rotation[2]))
    monkeypatch.setattr(cad, "build_assembly", lambda _design: moved)
    evidence = build_assembly_evidence(design)
    center = next(item for item in evidence["checks"] if item["id"] == "gear.center-distance")
    assert center["state"] == "FAILED"
    assert center["observed"]["distance_mm"] == pytest.approx(center["expected"]["distance_mm"] + 10)


def test_ev_relationships_check_real_wheel_stack_frame_and_crossmember_geometry():
    design = get_family("electric_vehicle").default_design()
    evidence = AssemblyEvidence.model_validate(_ev_assembly(design))
    assert evidence.assembly_id == "vehicle-assembly"
    assert evidence.revision == evidence.geometry_revision == design.revision
    assert len(evidence.components) == 27
    assert {item.id for item in evidence.hierarchy if item.kind == "component"} == {item.id for item in evidence.components}
    assert all(item.geometry_valid and item.volume_mm3 > 0 for item in evidence.components)
    for check_id in (
        "ev.front-left.wheel-stack-concentric", "ev.rear-right.wheel-stack-concentric",
        "ev.frame-rail-symmetry", "ev.running-gear.wheel-and-axle-centers",
        "ev.running-gear.axle-reference-placement", "ev.chassis.front-crossmember-rail-joints",
        "ev.chassis.rear-crossmember-rail-joints", "ev.overall-envelope-containment",
    ):
        check = next(item for item in evidence.checks if item.id == check_id)
        assert check.state == "PASSED", (check.id, check.observed)
        assert check.revision == check.geometry_revision == design.revision
    interface = next(item for item in evidence.checks if item.id == "ev.propulsion-frame-interface")
    assert interface.state == "UNOBSERVABLE"
    assert evidence.overall_state == "PARTIAL"


def test_ev_crossmember_and_wheel_placement_violations_are_detected_in_actual_solids():
    design = get_family("electric_vehicle").default_design()
    solids = dict(vehicle_component_solids(design))
    solids["front-crossmember"] = solids["front-crossmember"].translate((4000, 0, 0))
    solids["tire-front-left"] = solids["tire-front-left"].translate((25, 0, 0))
    evidence = _ev_assembly(design, solids)
    crossmember = next(item for item in evidence.checks if item.id == "ev.chassis.front-crossmember-rail-joints")
    tire = next(item for item in evidence.checks if item.id == "ev.running-gear.wheel-and-axle-centers")
    assert crossmember.state == "FAILED"
    assert tire.state == "FAILED"


def test_typed_assembly_rejects_missing_references_and_false_overall_pass():
    design = get_family("spur_gear_pair").default_design()
    payload = copy.deepcopy(build_assembly_evidence(design))
    payload["relationships"][0]["component_ids"] = ["pinion", "missing-part"]
    with pytest.raises(ValueError, match="missing components"):
        AssemblyEvidence.model_validate(payload)

    payload = copy.deepcopy(build_assembly_evidence(design))
    payload["overall_state"] = "PASSED"
    with pytest.raises(ValueError, match="cannot be PASSED"):
        AssemblyEvidence.model_validate(payload)


def test_project_api_returns_current_revision_assembly_checks(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "data" / "project.json")
    client = TestClient(app)
    response = client.get("/api/v1/project")
    assert response.status_code == 200
    project = response.json()
    assembly = project["assembly_verification"]
    assert assembly["revision"] == project["revision"]
    assert assembly["geometry_revision"] == project["revision"]
    assert assembly["overall_state"] == "PARTIAL"
    assert all(check["revision"] == check["geometry_revision"] == project["revision"] for check in assembly["checks"])
