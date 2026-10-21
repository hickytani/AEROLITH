import json

from fastapi.testclient import TestClient

from aeropkmech import store
from aeropkmech.main import app
from aeropkmech.model_platform import ModelRegistry, ModelUnavailable, OllamaProvider, OllamaRequirementProvider


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "data" / "project.json")
    monkeypatch.setattr("aeropkmech.main.LEARNING", tmp_path / "learning")
    monkeypatch.setattr("aeropkmech.main.MODEL_REGISTRY", ModelRegistry(tmp_path / "models" / "registry.json"))
    monkeypatch.delenv("AEROPKMECH_OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("AEROPKMECH_ENABLE_MODEL_EXTRACTION", raising=False)
    return TestClient(app)


def test_component_explanation_uses_canonical_context_with_fallback(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    result = client.post("/api/v1/components/explain", json={"component_id": "pinion", "question": "What does this component do?"})
    assert result.status_code == 200
    assert result.json()["provider"] == "deterministic-context"
    assert result.json()["revision"] == 1
    assert "strength" in result.json()["limitations"][0]
    assert client.post("/api/v1/components/explain", json={"component_id": "arbitrary", "question": "Explain this component"}).status_code == 404


def test_training_capture_is_disabled_by_default_then_redacted_and_quarantined(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    body = {"opt_in": True, "input_text": "token=super-secret person@example.test", "structured_output": {"note": "Bearer abcdef12345"}}
    assert client.post("/api/v1/learning/traces", json=body).status_code == 403
    monkeypatch.setenv("AEROPKMECH_ENABLE_TRAINING_CAPTURE", "true")
    result = client.post("/api/v1/learning/traces", json=body)
    assert result.status_code == 200
    trace_id = result.json()["id"]
    trace = json.loads((tmp_path / "learning" / "raw-traces" / f"{trace_id}.json").read_text(encoding="utf-8"))
    encoded = json.dumps(trace)
    assert "super-secret" not in encoded and "abcdef12345" not in encoded and "person@example.test" not in encoded
    assert client.delete(f"/api/v1/learning/traces/{trace_id}").json()["quarantined"] is True
    assert not (tmp_path / "learning" / "raw-traces" / f"{trace_id}.json").exists()


def test_trace_curation_requires_explicit_approval_and_reviewed_schema(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("AEROPKMECH_ENABLE_TRAINING_CAPTURE", "true")
    result = client.post("/api/v1/learning/traces", json={"opt_in": True, "input_text": "Explain pinion"})
    trace_id = result.json()["id"]
    curation = {"human_reviewed": True, "reviewer": "local reviewer", "source_license": "CC0-1.0", "task_category": "component_understanding", "expected_output": {"answer": "Input driver"}}
    assert client.post(f"/api/v1/learning/traces/{trace_id}/curate", json=curation).status_code == 409
    approved = client.post("/api/v1/learning/traces", json={"opt_in": True, "input_text": "Explain pinion"})
    approved_id = approved.json()["id"]
    assert client.post(f"/api/v1/learning/traces/{approved_id}/review", json={"decision": "APPROVED", "reviewer": "engineer", "review_note": "Verified expected output."}).status_code == 200
    result = client.post(f"/api/v1/learning/traces/{approved_id}/curate", json=curation)
    assert result.status_code == 200
    record = json.loads((tmp_path / "learning" / "curated" / "engineering-v2.jsonl").read_text(encoding="utf-8"))
    assert record["provenance"]["review_status"] == "APPROVED"


def test_model_registry_api_requires_checksummed_review_promotion_and_supports_rollback(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    metadata = {"model_id": "qwen4b-adapter-a", "runtime_model": "aeropkmech:qwen3-4b-a", "base_model": "Qwen/Qwen3-4B", "base_revision": "a" * 40,
        "dataset_version": "engineering-v2.0.0", "dataset_sha256": "b" * 64, "training_config_sha256": "c" * 64,
        "adapter_sha256": "d" * 64, "evaluation_suite": "engineering-eval-v1", "metrics": {"exact": 0.8}, "environment": {"gpu": "mock"}}
    assert client.post("/api/v1/models/registry/candidates", json=metadata).status_code == 201
    assert client.patch("/api/v1/models/registry/qwen4b-adapter-a", json={"state": "ACTIVE", "metrics": {"exact": 0.8}, "decision": "ok"}).status_code == 409
    for state in ("EVALUATED", "APPROVED", "ACTIVE"):
        result = client.patch("/api/v1/models/registry/qwen4b-adapter-a", json={"state": state, "metrics": {"exact": 0.8}, "decision": "reviewed"})
        assert result.status_code == 200
    assert client.get("/api/v1/models/registry").json()["active_model_id"] == "qwen4b-adapter-a"


def test_model_status_and_tool_proposals_fail_closed(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.get("/api/v1/model/status").json()["status"] == "DISABLED"
    good = client.post("/api/v1/engineering/tools/validate-proposal", json={"tool": "recalculate", "expected_revision": 1, "reason": "Refresh calculations."})
    assert good.status_code == 200 and good.json()["executed"] is False
    bad = client.post("/api/v1/engineering/tools/validate-proposal", json={"tool": "run_shell", "expected_revision": 1, "reason": "do it"})
    assert bad.status_code == 422


def test_model_status_does_not_call_running_ollama_ready_when_model_missing(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("AEROPKMECH_OLLAMA_MODEL", "qwen3:4b")
    async def probe(self):
        return {"service_reachable": True, "model_installed": False, "status": "MODEL_NOT_INSTALLED"}
    monkeypatch.setattr(OllamaProvider, "probe", probe)
    result = client.get("/api/v1/model/status").json()
    assert result["service_reachable"] is True
    assert result["model_installed"] is False
    assert result["available"] is False
    assert result["status"] == "MODEL_NOT_INSTALLED"
    assert result["inference_tested"] is False


def test_component_answer_reports_resource_failure_and_uses_canonical_fallback(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("AEROPKMECH_OLLAMA_MODEL", "qwen3:0.6b")
    async def probe(self):
        return {"service_reachable": True, "model_installed": True, "status": "MODEL_INSTALLED_NOT_INFERRED"}
    async def fail(self, prompt, *, system, max_output_chars=6000):
        raise ModelUnavailable("Local model inference failed.", "RESOURCE_EXHAUSTED")
    monkeypatch.setattr(OllamaProvider, "probe", probe)
    monkeypatch.setattr(OllamaProvider, "generate", fail)
    before = client.get("/api/v1/project").json()
    result = client.post("/api/v1/components/explain", json={"component_id": "pinion", "question": "What does this component do?"})
    after = client.get("/api/v1/project").json()
    assert result.status_code == 200
    assert result.json()["provider"] == "deterministic-context"
    assert result.json()["model_status"] == "RESOURCE_EXHAUSTED"
    assert result.json()["inference_succeeded"] is False
    assert result.json()["revision"] == before["revision"] == after["revision"]


def test_model_requirement_extraction_falls_back_with_specific_failure_status(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("AEROPKMECH_OLLAMA_MODEL", "qwen3:0.6b")
    monkeypatch.setenv("AEROPKMECH_ENABLE_MODEL_EXTRACTION", "true")
    async def fail(self, text):
        raise ModelUnavailable("Local model inference failed.", "RESOURCE_EXHAUSTED")
    monkeypatch.setattr(OllamaRequirementProvider, "propose", fail)
    before = client.get("/api/v1/project").json()
    result = client.post("/api/v1/project/interpret", json={"text": "18 tooth pinion and 54 tooth gear, module 2 mm, 8 Nm, 900 rpm, 12 mm face width"})
    after = client.get("/api/v1/project").json()
    assert result.status_code == 200
    assert result.json()["model_status"] == "RESOURCE_EXHAUSTED"
    assert result.json()["inference_succeeded"] is False
    assert "pinion_teeth" in result.json()["evidence"]
    assert after["revision"] == before["revision"]


def test_cors_allows_local_trace_delete_method(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    response = client.options("/api/v1/learning/traces/trace-" + "a" * 32,
        headers={"Origin": "http://127.0.0.1:3000", "Access-Control-Request-Method": "DELETE"})
    assert response.status_code == 200
    assert "DELETE" in response.headers["access-control-allow-methods"]


def test_change_impact_preview_is_revision_bound_and_does_not_mutate(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    result = client.post("/api/v1/project/change-impact", json={"expected_revision": 1, "changed_parameters": ["module_mm", "gear_teeth"]})
    assert result.status_code == 200
    assert result.json()["design_mutated"] is False
    assert result.json()["outputs_will_become_stale_after_commit"] is True
    assert client.get("/api/v1/project").json()["revision"] == 1
    assert client.post("/api/v1/project/change-impact", json={"expected_revision": 99, "changed_parameters": ["module_mm"]}).status_code == 409
    assert client.post("/api/v1/project/change-impact", json={"expected_revision": 1, "changed_parameters": ["secret_file"]}).status_code == 422


def test_dataset_status_validates_both_versioned_datasets():
    client = TestClient(app)
    for version in ("1.0.0", "engineering-v2.0.0"):
        result = client.get("/api/v1/learning/dataset/status", params={"version": version})
        assert result.status_code == 200
        assert result.json()["examples"] > 0
