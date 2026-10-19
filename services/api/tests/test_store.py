import json

import pytest
from pydantic import ValidationError

from aeropkmech import store
from aeropkmech.domain import Design


def configure_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "data" / "project.json")


def test_atomic_write_failure_preserves_last_valid_state(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    original = store.default_design()
    store.save(original)
    original_bytes = store.STATE_FILE.read_bytes()
    changed = original.model_copy(deep=True)
    changed.revision = 2

    def fail_replace(_source, _destination):
        raise OSError("simulated atomic replace failure")

    monkeypatch.setattr(store.os, "replace", fail_replace)
    with pytest.raises(store.ProjectPersistenceError):
        store.save(changed)
    assert store.STATE_FILE.read_bytes() == original_bytes
    assert store.load().revision == 1
    assert not list(store.DATA_DIR.glob("*.tmp"))


def test_invalid_full_candidate_is_rejected_without_overwriting(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    original = store.default_design()
    store.save(original)
    original_bytes = store.STATE_FILE.read_bytes()
    invalid = original.model_copy(deep=True)
    invalid.requirements.gear_ratio = 9

    with pytest.raises(store.ProjectPersistenceError):
        store.save(invalid)
    assert store.STATE_FILE.read_bytes() == original_bytes


def test_malformed_persisted_project_fails_explicitly(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    store.DATA_DIR.mkdir(parents=True)
    store.STATE_FILE.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(store.ProjectStateError):
        store.load()
    assert store.STATE_FILE.read_text(encoding="utf-8") == "{not valid json"


def test_schema_invalid_persisted_project_is_not_silently_replaced(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    store.DATA_DIR.mkdir(parents=True)
    store.STATE_FILE.write_text(json.dumps({"revision": 1}), encoding="utf-8")

    with pytest.raises(store.ProjectStateError):
        store.load()
    assert json.loads(store.STATE_FILE.read_text(encoding="utf-8")) == {"revision": 1}


def test_design_model_itself_rejects_missing_required_properties():
    with pytest.raises(ValidationError):
        Design.model_validate({"revision": 1})
