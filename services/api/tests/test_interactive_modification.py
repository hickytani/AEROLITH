"""Tests for the interactive component modification workflow, change-impact preview,
CAD assembly regeneration, revision propagation, and BOM documentation.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest
from fastapi import HTTPException

from aeropkmech import store
from aeropkmech import artifacts as artifact_store
from aeropkmech.cad import build_assembly
from aeropkmech.domain import Design
from aeropkmech.main import apply_component_modification, preview_component_modification, gear_bom_export
from aeropkmech.modifications import (
    GEAR_COMPONENT_PARAMETER_MAP,
    ComponentEditApplyRequest,
    ComponentEditPreviewRequest,
    gear_bom,
    preview_component_edit,
)


def configure_test_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "1")
    data_dir = tmp_path / "data"
    state_file = data_dir / "project.json"
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr(store, "DATA_DIR", data_dir)
    monkeypatch.setattr(store, "STATE_FILE", state_file)
    from aeropkmech import main
    monkeypatch.setattr(main, "ARTIFACTS", artifacts_dir)
    return data_dir, state_file, artifacts_dir


def test_component_parameter_map_contract():
    """Verify supported parameter definitions, bounds, and step sizes for pinion and gear."""
    assert "pinion" in GEAR_COMPONENT_PARAMETER_MAP
    assert "gear" in GEAR_COMPONENT_PARAMETER_MAP

    pinion_params = GEAR_COMPONENT_PARAMETER_MAP["pinion"]
    assert pinion_params["teeth"] == ("pinion_teeth", "count", 8, 80, 1)
    assert pinion_params["module_mm"] == ("module_mm", "mm", 0.5, 6.0, 0.1)
    assert pinion_params["face_width_mm"] == ("face_width_mm", "mm", 2.0, 60.0, 1.0)

    gear_params = GEAR_COMPONENT_PARAMETER_MAP["gear"]
    assert gear_params["teeth"] == ("gear_teeth", "count", 8, 120, 1)


def test_preview_valid_face_width_change(tmp_path, monkeypatch):
    """Scenario 1 preview: Changing pinion face width from 12 mm to 16 mm."""
    _, _, artifacts_dir = configure_test_environment(tmp_path, monkeypatch)
    design = store.default_design()

    preview = preview_component_edit(
        current=design,
        component_id="pinion",
        parameters={"face_width_mm": 16.0},
        artifacts_dir=artifacts_dir,
    )

    assert preview["valid"] is True
    assert preview["lifecycle_state"] == "VALIDATED"
    assert preview["component_id"] == "pinion"
    assert preview["current_revision"] == 1
    assert preview["target_revision"] == 2
    assert preview["design_mutated"] is False

    # Parameter change record
    param_change = next((p for p in preview["parameter_changes"] if p["parameter"] == "face_width_mm"), None)
    assert param_change is not None
    assert param_change["current_value"] == 12.0
    assert param_change["proposed_value"] == 16.0
    assert param_change["changed"] is True

    # Dependent changes: Lewis bending stresses decrease inversely with face width (12/16 = 0.75)
    dep_names = {d["parameter"] for d in preview["dependent_changes"]}
    assert "pinion_bending_stress_MPa" in dep_names
    assert "gear_bending_stress_MPa" in dep_names

    pinion_stress = next(d for d in preview["dependent_changes"] if d["parameter"] == "pinion_bending_stress_MPa")
    assert pinion_stress["delta"] < 0  # stress decreased
    assert pinion_stress["proposed_value"] == pytest.approx(pinion_stress["current_value"] * 12.0 / 16.0, rel=1e-3)

    # Both components are affected by a face width change
    assert set(preview["affected_components"]) == {"pinion", "gear"}


def test_preview_valid_tooth_count_change(tmp_path, monkeypatch):
    """Scenario 2 preview: Changing pinion tooth count from 18 to 20."""
    _, _, artifacts_dir = configure_test_environment(tmp_path, monkeypatch)
    design = store.default_design()

    preview = preview_component_edit(
        current=design,
        component_id="pinion",
        parameters={"teeth": 20},
        artifacts_dir=artifacts_dir,
    )

    assert preview["valid"] is True
    assert preview["lifecycle_state"] == "VALIDATED"

    # Dependent changes: center distance increases from 72 to 74 mm
    cd_change = next((d for d in preview["dependent_changes"] if d["parameter"] == "center_distance_mm"), None)
    assert cd_change is not None
    assert cd_change["current_value"] == pytest.approx(72.0)
    assert cd_change["proposed_value"] == pytest.approx(74.0)  # 2.0 * (20 + 54) / 2 = 74.0 mm
    assert cd_change["delta"] == pytest.approx(2.0)

    # Gear ratio changes from 3.0 (54/18) to 2.7 (54/20)
    ratio_change = next((d for d in preview["dependent_changes"] if d["parameter"] == "gear_ratio"), None)
    assert ratio_change is not None
    assert ratio_change["current_value"] == pytest.approx(3.0)
    assert ratio_change["proposed_value"] == pytest.approx(2.7)

    # Pinion pitch diameter changes from 36 to 40 mm
    pitch_change = next((d for d in preview["dependent_changes"] if d["parameter"] == "pinion.pitch_diameter_mm"), None)
    assert pitch_change is not None
    assert pitch_change["current_value"] == pytest.approx(36.0)
    assert pitch_change["proposed_value"] == pytest.approx(40.0)


def test_preview_invalid_parameter_rejected(tmp_path, monkeypatch):
    """Verify out-of-range and invalid parameters are rejected with actionable errors."""
    _, _, artifacts_dir = configure_test_environment(tmp_path, monkeypatch)
    design = store.default_design()

    # Tooth count below minimum (8)
    p1 = preview_component_edit(design, "pinion", {"teeth": 6}, artifacts_dir)
    assert p1["valid"] is False
    assert p1["lifecycle_state"] == "INVALID"
    assert any("outside allowed range [8, 80]" in e for e in p1["errors"])

    # Tooth count above maximum for pinion (80)
    p2 = preview_component_edit(design, "pinion", {"teeth": 85}, artifacts_dir)
    assert p2["valid"] is False
    assert any("outside allowed range [8, 80]" in e for e in p2["errors"])

    # Non-integer tooth count
    p3 = preview_component_edit(design, "pinion", {"teeth": 18.5}, artifacts_dir)
    assert p3["valid"] is False
    assert any("integer" in e for e in p3["errors"])

    # Module out of range
    p4 = preview_component_edit(design, "pinion", {"module_mm": 7.5}, artifacts_dir)
    assert p4["valid"] is False
    assert any("outside allowed range [0.5, 6.0]" in e for e in p4["errors"])

    # Bore diameter exceeding safe rim limit
    p5 = preview_component_edit(design, "pinion", {"bore_diameter_mm": 45.0}, artifacts_dir)
    assert p5["valid"] is False
    assert any("safe rim thickness" in e for e in p5["errors"])


def test_apply_component_modification_end_to_end_scenario_1(tmp_path, monkeypatch):
    """End-to-End Scenario 1:
    1. Open default 18/54 gear design.
    2. Select pinion.
    3. Modify face width from 12 mm to 16 mm.
    4. Validate preview.
    5. Explicitly accept modification.
    6. Verify CAD assembly regenerates with face width = 16 mm.
    7. Verify engineering quantities recalculate (Lewis stress decreases).
    8. Confirm new revision 2 recorded with history provenance.
    9. Confirm reload from disk preserves the committed revision.
    """
    _, _, artifacts_dir = configure_test_environment(tmp_path, monkeypatch)
    initial_design = store.default_design()
    store.save(initial_design)
    assert store.load().revision == 1

    # Call the apply endpoint
    req = ComponentEditApplyRequest(
        component_id="pinion",
        expected_revision=1,
        parameters={"face_width_mm": 16.0},
    )
    result = apply_component_modification(req)

    # 1. Revision advanced
    assert result["revision"] == 2
    assert result["requirements"]["face_width_mm"] == 16.0

    # 2. Modification summary present
    summary = result.get("modification_summary")
    assert summary is not None
    assert summary["lifecycle_state"] == "REGENERATED"
    assert summary["component_id"] == "pinion"
    assert summary["previous_revision"] == 1
    assert summary["new_revision"] == 2
    assert summary["changed_parameters"] == {"face_width_mm": 16.0}

    # 3. Persistent state on disk
    persisted = store.load()
    assert persisted.revision == 2
    assert persisted.requirements.face_width_mm == 16.0
    assert len(persisted.history) == 1
    assert persisted.history[0]["revision"] == 1
    assert persisted.history[0]["component_id"] == "pinion"
    assert persisted.history[0]["changed_parameters"] == ["face_width_mm"]

    # 4. CAD assembly checks
    evidence = result["assembly_verification"]
    assert evidence["revision"] == 2
    face_width_check = next(c for c in evidence["checks"] if c["id"] == "gear.face-width")
    assert face_width_check["state"] == "PASSED"
    assert face_width_check["observed"]["pinion_width_mm"] == pytest.approx(16.0, abs=0.01)
    assert face_width_check["observed"]["gear_width_mm"] == pytest.approx(16.0, abs=0.01)

    # 5. Engineering recalculation: Lewis stress updated
    derived = result["derived"]
    # 59.93 * 12 / 16 = 44.95 MPa
    assert derived["pinion_bending_stress_MPa"] == pytest.approx(44.95, rel=1e-2)


def test_apply_component_modification_dependent_placement_scenario_2(tmp_path, monkeypatch):
    """End-to-End Scenario 2 (Dependent change):
    1. Change pinion teeth from 18 to 20.
    2. Verify driven gear placement transform origin updates to new center distance (74 mm).
    3. Verify CAD assembly verification passes with new center distance.
    4. Verify gear ratio updates to 2.7.
    """
    _, _, artifacts_dir = configure_test_environment(tmp_path, monkeypatch)
    initial_design = store.default_design()
    store.save(initial_design)

    req = ComponentEditApplyRequest(
        component_id="pinion",
        expected_revision=1,
        parameters={"teeth": 20},
    )
    result = apply_component_modification(req)

    assert result["revision"] == 2
    assert result["components"][0]["teeth"] == 20
    assert result["components"][1]["teeth"] == 54

    # Derived center distance
    derived = result["derived"]
    assert derived["center_distance_mm"] == pytest.approx(74.0)
    assert derived["gear_ratio"] == pytest.approx(2.7)

    # Assembly verification
    evidence = result["assembly_verification"]
    cd_check = next(c for c in evidence["checks"] if c["id"] == "gear.center-distance")
    assert cd_check["state"] == "PASSED"
    assert cd_check["expected"]["distance_mm"] == pytest.approx(74.0)
    assert cd_check["observed"]["distance_mm"] == pytest.approx(74.0, abs=0.05)
    assert cd_check["observed"]["gear_origin_mm"][0] == pytest.approx(74.0, abs=0.05)

    # Solid validity check
    valid_check = next(c for c in evidence["checks"] if c["id"] == "gear.solids.valid")
    assert valid_check["state"] == "PASSED"


def test_revision_conflict_409_rejection(tmp_path, monkeypatch):
    """Verify that attempting to modify a stale revision raises 409 Conflict."""
    _, _, artifacts_dir = configure_test_environment(tmp_path, monkeypatch)
    design = store.default_design()
    design.revision = 3
    design.parameter_quantities = {}
    design.parameter_records = {}
    design = Design.model_validate(design.model_dump(mode="json"))
    store.save(design)

    with pytest.raises(HTTPException) as exc_info:
        preview_component_modification(
            ComponentEditPreviewRequest(
                component_id="pinion",
                expected_revision=2,  # stale
                parameters={"face_width_mm": 15.0},
            )
        )
    assert exc_info.value.status_code == 409

    with pytest.raises(HTTPException) as exc_info2:
        apply_component_modification(
            ComponentEditApplyRequest(
                component_id="pinion",
                expected_revision=2,  # stale
                parameters={"face_width_mm": 15.0},
            )
        )
    assert exc_info2.value.status_code == 409


def test_gear_bom_generation_and_export(tmp_path, monkeypatch):
    """Verify Bill of Materials structure, dimensions, stresses, and export endpoint."""
    _, _, artifacts_dir = configure_test_environment(tmp_path, monkeypatch)
    design = store.default_design()
    store.save(design)

    bom_data = gear_bom(design)
    assert bom_data["bom_version"] == "gear-bom-0.1"
    assert bom_data["revision"] == 1
    assert len(bom_data["components"]) == 2

    pinion_bom = next(c for c in bom_data["components"] if c["id"] == "pinion")
    assert pinion_bom["teeth"] == 18
    assert pinion_bom["module_mm"] == 2.0
    assert pinion_bom["face_width_mm"] == 12.0
    assert pinion_bom["pitch_diameter_mm"] == 36.0
    assert pinion_bom["outer_diameter_mm"] == 40.0
    assert pinion_bom["root_diameter_mm"] == 31.0
    assert pinion_bom["quantity"] == 1
    assert "lewis_bending_stress_MPa" in pinion_bom
    assert pinion_bom["lewis_bending_stress_MPa"] == pytest.approx(59.93, rel=1e-2)

    gear_bom_item = next(c for c in bom_data["components"] if c["id"] == "gear")
    assert gear_bom_item["teeth"] == 54
    assert gear_bom_item["pitch_diameter_mm"] == 108.0
    assert gear_bom_item["lewis_bending_stress_MPa"] == pytest.approx(44.71, rel=1e-2)

    # Test gear_bom_export() endpoint publishes artifact
    response = gear_bom_export()
    assert response.status_code == 200
    assert response.headers["X-Artifact-Kind"] == "gear-bom"
    assert response.headers["X-Design-Revision"] == "1"


def test_stale_artifact_detection_after_modification(tmp_path, monkeypatch):
    """Verify that prior artifacts are marked stale after a component modification."""
    _, _, artifacts_dir = configure_test_environment(tmp_path, monkeypatch)
    design = store.default_design()
    store.save(design)

    # Publish an artifact at revision 1
    artifact_store.publish(
        b"sample-drawing-bytes",
        artifacts_dir,
        design,
        "gear-reference-drawing",
        "pdf",
        "0.3",
    )

    artifacts_r1 = artifact_store.list_artifacts(artifacts_dir, design)
    assert len(artifacts_r1) == 1
    assert artifacts_r1[0]["stale"] is False

    # Advance design to revision 2 via component edit
    apply_component_modification(
        ComponentEditApplyRequest(
            component_id="pinion",
            expected_revision=1,
            parameters={"face_width_mm": 18.0},
        )
    )

    r2_design = store.load()
    assert r2_design.revision == 2

    # R1 artifact is now marked stale
    artifacts_r2 = artifact_store.list_artifacts(artifacts_dir, r2_design)
    assert len(artifacts_r2) == 1
    assert artifacts_r2[0]["stale"] is True
