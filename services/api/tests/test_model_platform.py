import pytest
import asyncio
import httpx
from concurrent.futures import ThreadPoolExecutor

from aeropkmech.model_platform import (
    ModelRegistry, ModelState, ModelUnavailable, OllamaProvider, component_context, configured_runtime_model, redact_sensitive,
    validate_split_files, validate_tool_proposal,
)
from aeropkmech.store import default_design


def test_redacts_credentials_and_personal_email():
    text = "api_key=super-secret-value Bearer abcdef.123 person@example.test"
    cleaned = redact_sensitive(text)
    assert "super-secret-value" not in cleaned
    assert "abcdef.123" not in cleaned
    assert "person@example.test" not in cleaned
    assert "[REDACTED_SECRET]" in cleaned


def test_local_model_adapter_rejects_non_loopback_url():
    with pytest.raises(ValueError):
        OllamaProvider("qwen3:4b", "http://192.168.1.2:11434")
    assert OllamaProvider("qwen3:4b").base_url == "http://127.0.0.1:11434"


@pytest.mark.parametrize(("detail", "expected"), [
    ("cudaMalloc failed: out of memory", "RESOURCE_EXHAUSTED"),
    ("The system detected an overrun of a stack-based buffer in this application (0xc0000409)", "RUNTIME_CRASH"),
    ("model qwen3:4b not found", "MODEL_NOT_INSTALLED"),
])
def test_ollama_inference_errors_are_classified_without_exposing_runtime_text(monkeypatch, detail, expected):
    original_client = httpx.AsyncClient

    def make_client(**kwargs):
        request = httpx.Request("POST", "http://127.0.0.1:11434/api/generate")
        response = httpx.Response(500, json={"error": detail}, request=request)
        transport = httpx.MockTransport(lambda _: response)
        return original_client(transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", make_client)
    provider = OllamaProvider("qwen3:0.6b", timeout=2)
    with pytest.raises(ModelUnavailable) as raised:
        asyncio.run(provider.generate("{}", system="Return JSON."))
    assert raised.value.code == expected
    assert detail not in str(raised.value)


def test_ollama_probe_distinguishes_missing_model_from_unavailable_service(monkeypatch):
    original_client = httpx.AsyncClient

    def make_client(**kwargs):
        request = httpx.Request("GET", "http://127.0.0.1:11434/api/tags")
        response = httpx.Response(200, json={"models": [{"name": "qwen3:0.6b", "model": "qwen3:0.6b"}]}, request=request)
        return original_client(transport=httpx.MockTransport(lambda _: response), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", make_client)
    installed = asyncio.run(OllamaProvider("qwen3:0.6b").probe())
    missing = asyncio.run(OllamaProvider("qwen3:4b").probe())
    assert installed == {"service_reachable": True, "model_installed": True, "status": "MODEL_INSTALLED_NOT_INFERRED"}
    assert missing["service_reachable"] is True
    assert missing["model_installed"] is False
    assert missing["status"] == "MODEL_NOT_INSTALLED"


@pytest.mark.parametrize(("exception_type", "expected"), [
    (httpx.ReadTimeout, "TIMEOUT"),
    (httpx.ConnectError, "SERVICE_UNAVAILABLE"),
])
def test_ollama_generate_classifies_timeout_and_unavailable_service(monkeypatch, exception_type, expected):
    original_client = httpx.AsyncClient

    def make_client(**kwargs):
        def fail(request):
            raise exception_type("local inference failure", request=request)
        return original_client(transport=httpx.MockTransport(fail), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", make_client)
    provider = OllamaProvider("qwen3:0.6b", timeout=1)
    with pytest.raises(ModelUnavailable) as raised:
        asyncio.run(provider.generate("{}", system="JSON only"))
    assert raised.value.code == expected


def test_ollama_generate_classifies_malformed_service_json(monkeypatch):
    original_client = httpx.AsyncClient

    def make_client(**kwargs):
        response = httpx.Response(200, content=b"not-json", headers={"Content-Type": "application/json"})
        return original_client(transport=httpx.MockTransport(lambda _: response), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", make_client)
    provider = OllamaProvider("qwen3:0.6b", timeout=1)
    with pytest.raises(ModelUnavailable) as raised:
        asyncio.run(provider.generate("{}", system="JSON only"))
    assert raised.value.code == "MALFORMED_SERVICE_RESPONSE"


def test_ollama_probe_marks_malformed_tags_response_not_ready(monkeypatch):
    original_client = httpx.AsyncClient

    def make_client(**kwargs):
        response = httpx.Response(200, content=b"not-json", headers={"Content-Type": "application/json"})
        return original_client(transport=httpx.MockTransport(lambda _: response), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", make_client)
    result = asyncio.run(OllamaProvider("qwen3:0.6b").probe())
    assert result == {"service_reachable": True, "model_installed": False, "status": "INVALID_SERVICE_RESPONSE"}


def test_tool_proposals_are_revision_bound_and_never_executed():
    result = validate_tool_proposal({"tool": "generate_component_mesh", "component_id": "pinion", "expected_revision": 2, "reason": "User requested mesh preview."})
    assert result["requires_user_confirmation"] is True
    assert result["executed"] is False
    with pytest.raises(ValueError):
        validate_tool_proposal({"tool": "run_shell", "expected_revision": 2, "reason": "x"})
    with pytest.raises(ValueError):
        validate_tool_proposal({"tool": "export_report", "expected_revision": 2, "reason": "x", "shell": "whoami"})


def test_registry_enforces_evaluation_approval_activation_and_rollback(tmp_path):
    registry = ModelRegistry(tmp_path / "registry.json")
    make = lambda model_id: {
        "model_id": model_id, "runtime_model": "qwen3:4b", "base_model": "Qwen/Qwen3-4B", "base_revision": "a" * 40,
        "dataset_version": "engineering-v2.0.0", "dataset_sha256": "b" * 64,
        "training_config_sha256": "c" * 64, "adapter_sha256": "d" * 64,
        "evaluation_suite": "engineering-eval-v1", "metrics": {"baseline_exact": 0.5}, "environment": {"python": "3.12"},
    }
    with pytest.raises(ValueError):
        registry.register({**make("candidate"), "adapter_sha256": "not-a-checksum"})
    registry.register(make("candidate-1"))
    with pytest.raises(ValueError):
        registry.transition("candidate-1", ModelState.ACTIVE, metrics={"accuracy": 1}, decision="approve")
    registry.transition("candidate-1", ModelState.EVALUATED, metrics={"accuracy": 0.9})
    registry.transition("candidate-1", ModelState.APPROVED, decision="reviewed")
    registry.transition("candidate-1", ModelState.ACTIVE, metrics={"accuracy": 0.9}, decision="approve")
    registry.register(make("candidate-2"))
    registry.transition("candidate-2", ModelState.EVALUATED, metrics={"accuracy": 0.91})
    registry.transition("candidate-2", ModelState.APPROVED, decision="reviewed")
    registry.transition("candidate-2", ModelState.ACTIVE, metrics={"accuracy": 0.91}, decision="approve")
    assert registry.rollback() == "candidate-1"
    state = registry.read()
    assert state["active_model_id"] == "candidate-1"
    assert state["rollback_model_id"] == "candidate-2"


def test_existing_dataset_version_and_split_integrity():
    from pathlib import Path
    dataset = Path(__file__).resolve().parents[3] / "data" / "learning"
    report = validate_split_files(dataset)
    assert report["dataset_version"] == "gear-requirements-synthetic-1.0"
    assert set(report["splits"]) == {"train", "validation", "test"}
    assert len(report["sha256"]) == 3


def test_v2_eight_category_fixture_has_disjoint_splits():
    from pathlib import Path
    import runpy
    validator = Path(__file__).resolve().parents[3] / "ml-training" / "scripts" / "validate_dataset.py"
    report = runpy.run_path(str(validator))["validate"](validator.parents[2] / "data" / "learning" / "engineering-v2")
    assert report["examples"] == 50
    assert report["counts"] == {"train": 30, "validation": 10, "test": 10}


def test_component_context_is_from_canonical_design():
    design = default_design()
    context = component_context(design, "pinion")
    assert context["revision"] == design.revision
    assert context["component"]["teeth"] == design.components[0].teeth
    with pytest.raises(KeyError):
        component_context(design, "unknown")




def test_active_registry_model_overrides_environment_baseline(tmp_path):
    registry = ModelRegistry(tmp_path / "registry.json")
    registry.register({"model_id": "adapter-v1", "runtime_model": "aeropkmech:qwen3-4b-adapter-v1", "base_model": "Qwen/Qwen3-4B",
        "base_revision": "a" * 40, "dataset_version": "v1", "dataset_sha256": "b" * 64,
        "training_config_sha256": "c" * 64, "adapter_sha256": "d" * 64, "evaluation_suite": "v1", "metrics": {}, "environment": {}})
    registry.transition("adapter-v1", ModelState.EVALUATED, metrics={"exact": 0.8})
    registry.transition("adapter-v1", ModelState.APPROVED, decision="approved")
    registry.transition("adapter-v1", ModelState.ACTIVE, metrics={"exact": 0.8}, decision="approved")
    assert configured_runtime_model(registry, "qwen3:0.6b") == ("aeropkmech:qwen3-4b-adapter-v1", "adapter-v1")


def test_concurrent_candidate_registration_keeps_registry_updates(tmp_path):
    registry = ModelRegistry(tmp_path / "registry.json")
    def register(index):
        registry.register({"model_id": f"candidate-{index}", "runtime_model": f"local:model-{index}",
            "base_model": "Qwen/Qwen3-4B", "base_revision": "a" * 40, "dataset_version": "v1",
            "dataset_sha256": "b" * 64, "training_config_sha256": "c" * 64,
            "adapter_sha256": "d" * 64, "evaluation_suite": "v1", "metrics": {}, "environment": {}})
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(register, range(8)))
    assert len(registry.read()["models"]) == 8


def test_evaluation_exact_subset_scorer_requires_each_expected_field():
    from pathlib import Path
    import runpy
    evaluator = Path(__file__).resolve().parents[3] / "ml-training" / "scripts" / "evaluate_models.py"
    scorer = runpy.run_path(str(evaluator))["subset_exact"]
    assert scorer({"ratio": 3, "supported": True}, {"ratio": 3, "supported": True, "reason": "matched"})
    assert not scorer({"ratio": 3}, {"ratio": 4})


def test_evaluation_exact_subset_scorer_requires_each_expected_field():
    from pathlib import Path
    import runpy
    evaluator = Path(__file__).resolve().parents[3] / "ml-training" / "scripts" / "evaluate_models.py"
    scorer = runpy.run_path(str(evaluator))["subset_exact"]
    assert scorer({"ratio": 3, "supported": True}, {"ratio": 3, "supported": True, "reason": "matched"})
    assert not scorer({"ratio": 3}, {"ratio": 4})
