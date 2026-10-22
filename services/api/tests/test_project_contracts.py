"""State and revision tests that intentionally do not initialize CadQuery."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from aeropkmech import store
from aeropkmech.artifacts import list_artifacts, publish
from aeropkmech.automotive import VehicleGenerationRequest, make_vehicle_design, propagate_vehicle_edits


def _vehicle(revision: int = 1):
    request = VehicleGenerationRequest(
        expected_revision=revision,
        overall_length_mm=4200, overall_width_mm=1800, occupant_capacity=2,
        target_range_km=300, body_height_mm=1400, wheelbase_mm=2520,
        front_track_mm=1575, rear_track_mm=1575, tire_outer_diameter_mm=650,
        tire_width_mm=225, ground_clearance_mm=150, frame_rail_width_mm=60,
        frame_rail_height_mm=80, body_width_mm=1260, body_length_mm=4200,
    )
    return make_vehicle_design(request, revision, [])


def _configure_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "data" / "project.json")


def test_ev_state_and_parameter_edit_round_trip_without_cad_runtime(tmp_path, monkeypatch):
    _configure_store(tmp_path, monkeypatch)
    original = _vehicle()
    original.id = "project-stable"
    original.parameter_records = {}
    from aeropkmech.automotive import VehicleDesign
    original = VehicleDesign.model_validate(original.model_dump(mode="json"))
    assert original.parameter_records["wheelbase_mm"].component_ids
    assert all(record.project_id == original.id and record.revision == 1 for record in original.parameter_records.values())
    store.save(original)

    loaded = store.load()
    candidate, propagated = propagate_vehicle_edits(loaded, {"wheelbase_mm": 2700})
    assert propagated == {}
    candidate.id = loaded.id
    store.save_if_revision(candidate, loaded.revision)
    persisted = store.load()
    assert persisted.id == original.id
    assert persisted.revision == original.revision + 1
    assert persisted.parameter_records["wheelbase_mm"].quantity.value == 2700
    assert persisted.parameter_records["wheelbase_mm"].revision == persisted.revision
    assert persisted.parameter_records["wheelbase_mm"].component_ids

    legacy = persisted.model_dump(mode="json")
    legacy.pop("parameter_quantities")
    legacy.pop("parameter_records")
    migrated = VehicleDesign.model_validate(legacy)
    assert migrated.parameter_quantities["overall_length_mm"].value == 4200
    assert migrated.parameter_records["overall_length_mm"].project_id == migrated.id
    assert migrated.parameter_records["overall_length_mm"].revision == migrated.revision

    unsupported_version = migrated.model_dump(mode="json")
    unsupported_version["schema_version"] = "99.0"
    with pytest.raises(ValidationError):
        VehicleDesign.model_validate(unsupported_version)

    dangling_component = migrated.model_dump(mode="json")
    dangling_component["parameter_records"]["overall_length_mm"]["component_ids"] = ["missing-component"]
    with pytest.raises(ValidationError):
        VehicleDesign.model_validate(dangling_component)


def test_compare_and_swap_rejects_stale_snapshot_wrong_revision_and_identity(tmp_path, monkeypatch):
    _configure_store(tmp_path, monkeypatch)
    initial = store.default_design()
    store.save(initial)
    latest = initial.model_copy(deep=True)
    latest.revision = 2
    latest.parameter_quantities = {}
    latest.parameter_records = {}
    from aeropkmech.domain import Design
    latest = Design.model_validate(latest.model_dump(mode="json"))
    store.save_if_revision(latest, 1)

    stale = initial.model_copy(deep=True)
    stale.revision = 2
    stale.parameter_quantities = {}
    stale.parameter_records = {}
    stale = Design.model_validate(stale.model_dump(mode="json"))
    with pytest.raises(store.ProjectRevisionConflict):
        store.save_if_revision(stale, 1)

    wrong_revision = store.load().model_copy(deep=True)
    wrong_revision.revision = 4
    with pytest.raises(store.ProjectPersistenceError, match="advance exactly one revision"):
        store.save_if_revision(wrong_revision, 2)

    wrong_identity = store.load().model_copy(deep=True)
    wrong_identity.id = "another-project"
    wrong_identity.revision = 3
    wrong_identity.parameter_quantities = {}
    wrong_identity.parameter_records = {}
    from aeropkmech.domain import Design
    wrong_identity = Design.model_validate(wrong_identity.model_dump(mode="json"))
    with pytest.raises(store.ProjectPersistenceError, match="preserve the active project identity"):
        store.save_if_revision(wrong_identity, 2)


def test_regeneration_retains_old_artifact_and_binds_new_artifact_to_parameter_ids(tmp_path, monkeypatch):
    _configure_store(tmp_path, monkeypatch)
    artifacts_dir = tmp_path / "artifacts"
    initial = store.default_design()
    store.save(initial)
    old_path, old_metadata = publish(b"old-step", artifacts_dir, initial, "assembly", "step", "generator-1")
    assert old_path.is_file()
    assert old_metadata["project_id"] == initial.id
    assert old_metadata["parameter_ids"]

    candidate = store.load().model_copy(deep=True)
    candidate.revision += 1
    candidate.requirements.module_mm = 2.5
    candidate.parameter_quantities = {}
    candidate.parameter_records = {}
    from aeropkmech.domain import Design
    candidate = Design.model_validate(candidate.model_dump(mode="json"))
    store.save_if_revision(candidate, initial.revision)
    new_path, new_metadata = publish(b"new-step", artifacts_dir, candidate, "assembly", "step", "generator-1")
    listed = list_artifacts(artifacts_dir, candidate)
    old_item = next(item for item in listed if item["artifact_id"] == old_metadata["artifact_id"])
    new_item = next(item for item in listed if item["artifact_id"] == new_metadata["artifact_id"])
    assert old_path.is_file() and new_path.is_file()
    assert old_item["stale"] is True and old_item["available"] is True
    assert new_item["stale"] is False and new_item["project_id"] == candidate.id
    assert set(new_item["parameter_ids"]) == {record.id for record in candidate.parameter_records.values()}
