"""Local-model, training-data, and promotion boundaries for AeroPKmech.

Model output is always an untrusted proposal. This module never mutates a
design or executes tools on a model's behalf.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import uuid
from functools import wraps
from threading import RLock
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field


class ModelUnavailable(RuntimeError):
    def __init__(self, message: str, code: str = "INFERENCE_FAILED"):
        super().__init__(message)
        self.code = code


class ComponentAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    answer: str = Field(min_length=1, max_length=4000)
    evidence: list[str] = Field(max_length=12)
    limitations: list[str] = Field(max_length=12)


class ModelProvider(Protocol):
    async def generate(self, prompt: str, *, system: str, max_output_chars: int = 6000) -> str: ...


def _runtime_failure_code(detail: str) -> str:
    lowered = detail.lower()
    if "out of memory" in lowered or "cudamalloc failed" in lowered or "failed to allocate" in lowered:
        return "RESOURCE_EXHAUSTED"
    if "stack-based buffer overrun" in lowered or "0xc0000409" in lowered:
        return "RUNTIME_CRASH"
    if "model" in lowered and ("not found" in lowered or "does not exist" in lowered):
        return "MODEL_NOT_INSTALLED"
    return "INFERENCE_FAILED"


class OllamaProvider:
    """Bounded Ollama local HTTP adapter; no remote provider or credentials."""

    def __init__(self, model: str, base_url: str = "http://127.0.0.1:11434", timeout: float = 45):
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", model):
            raise ValueError("Invalid local model identifier.")
        parsed = urlsplit(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Ollama inference must use a plain HTTP loopback endpoint.")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = min(max(timeout, 1), 90)

    async def probe(self) -> dict[str, Any]:
        """Check the local service and exact configured model independently."""
        try:
            async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
                result = await client.get(f"{self.base_url}/api/tags")
                result.raise_for_status()
                payload = result.json()
            models = payload.get("models") if isinstance(payload, dict) else None
            if not isinstance(models, list):
                return {"service_reachable": True, "model_installed": False, "status": "INVALID_SERVICE_RESPONSE"}
            installed = any(
                isinstance(item, dict) and self.model in {item.get("name"), item.get("model")}
                for item in models
            )
            return {
                "service_reachable": True,
                "model_installed": installed,
                "status": "MODEL_INSTALLED_NOT_INFERRED" if installed else "MODEL_NOT_INSTALLED",
            }
        except httpx.TimeoutException:
            return {"service_reachable": False, "model_installed": False, "status": "SERVICE_TIMEOUT"}
        except httpx.HTTPStatusError:
            return {"service_reachable": True, "model_installed": False, "status": "SERVICE_HTTP_ERROR"}
        except json.JSONDecodeError:
            return {"service_reachable": True, "model_installed": False, "status": "INVALID_SERVICE_RESPONSE"}
        except (httpx.HTTPError, ValueError):
            return {"service_reachable": False, "model_installed": False, "status": "SERVICE_UNAVAILABLE"}

    async def health(self) -> bool:
        status = await self.probe()
        return status["service_reachable"] and status["model_installed"]

    async def generate(self, prompt: str, *, system: str, max_output_chars: int = 6000) -> str:
        if len(prompt) > 12000 or len(system) > 3000:
            raise ValueError("Model context exceeds the configured character limit.")
        try:
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={"model": self.model, "system": system, "prompt": prompt,
                          "stream": False, "format": "json", "options": {"num_predict": 800}},
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ModelUnavailable("Local model inference timed out.", "TIMEOUT") from exc
        except httpx.ConnectError as exc:
            raise ModelUnavailable("Local inference service is unavailable.", "SERVICE_UNAVAILABLE") from exc
        except httpx.HTTPStatusError as exc:
            raise ModelUnavailable("Local model inference failed.", _runtime_failure_code(exc.response.text[:2000])) from exc
        except httpx.HTTPError as exc:
            raise ModelUnavailable("Local model inference failed.", "INFERENCE_FAILED") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise ModelUnavailable("Local model returned malformed service JSON.", "MALFORMED_SERVICE_RESPONSE") from exc
        if isinstance(payload, dict) and isinstance(payload.get("error"), str):
            raise ModelUnavailable("Local model inference failed.", _runtime_failure_code(payload["error"][:2000]))
        text = payload.get("response") if isinstance(payload, dict) else None
        if not isinstance(text, str) or len(text) > max_output_chars:
            raise ModelUnavailable("Local model returned an invalid or oversized response.", "INVALID_MODEL_OUTPUT")
        return text


class OllamaRequirementProvider(OllamaProvider):
    async def propose(self, text: str) -> dict:
        prompt = json.dumps({"request": text, "required_fields": ["pinion_teeth", "gear_teeth", "gear_ratio", "input_torque_Nm", "input_speed_rpm", "module_mm", "face_width_mm"]}, ensure_ascii=False)
        system = ("Extract only explicit external spur-gear requirements. Return one JSON object with exactly those seven keys, "
                  "using numbers or null. Never infer defaults or calculate a missing value. No prose.")
        try:
            output = await self.generate(prompt, system=system, max_output_chars=3000)
            value = json.loads(output)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ModelUnavailable("Local model did not return valid requirement JSON.", "INVALID_MODEL_OUTPUT") from exc
        if not isinstance(value, dict):
            raise ModelUnavailable("Local model requirement output must be a JSON object.", "INVALID_MODEL_OUTPUT")
        return value


class ModelState(StrEnum):
    BASELINE = "BASELINE"
    FINE_TUNED_CANDIDATE = "FINE_TUNED_CANDIDATE"
    EVALUATED = "EVALUATED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ACTIVE = "ACTIVE"


_TRANSITIONS = {
    ModelState.FINE_TUNED_CANDIDATE: {ModelState.EVALUATED, ModelState.REJECTED},
    ModelState.EVALUATED: {ModelState.APPROVED, ModelState.REJECTED},
    ModelState.APPROVED: {ModelState.ACTIVE, ModelState.REJECTED},
    ModelState.ACTIVE: {ModelState.REJECTED},
    ModelState.BASELINE: set(), ModelState.REJECTED: set(),
}


def _registry_locked(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapped


class ModelRegistry:
    """Small atomic local registry; adapters and base weights stay out of Git."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = RLock()

    @_registry_locked
    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": 1, "active_model_id": None, "rollback_model_id": None, "models": []}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if value.get("schema_version") != 1 or not isinstance(value.get("models"), list):
            raise ValueError("Model registry is malformed.")
        return value

    @_registry_locked
    def _write(self, value: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with tmp.open("xb") as stream:
                stream.write(json.dumps(value, indent=2).encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.path)
        finally:
            tmp.unlink(missing_ok=True)

    @_registry_locked
    def register(self, metadata: dict) -> dict:
        required = {"model_id", "runtime_model", "base_model", "base_revision", "dataset_version", "dataset_sha256", "training_config_sha256", "adapter_sha256", "evaluation_suite", "metrics", "environment"}
        if not required.issubset(metadata) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", metadata["model_id"]):
            raise ValueError("Model metadata is incomplete or contains an invalid identifier.")
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", metadata["runtime_model"]):
            raise ValueError("runtime_model must identify a locally installed inference model.")
        if not re.fullmatch(r"[0-9a-f]{40}", str(metadata["base_revision"])):
            raise ValueError("base_revision must be a pinned 40-character hexadecimal commit.")
        for key in ("dataset_sha256", "training_config_sha256", "adapter_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", str(metadata[key])):
                raise ValueError(f"{key} must be a SHA-256 digest.")
        value = self.read()
        if any(item["model_id"] == metadata["model_id"] for item in value["models"]):
            raise ValueError("Model IDs are immutable and cannot be registered twice.")
        record = {**metadata, "state": ModelState.FINE_TUNED_CANDIDATE.value, "created_at": datetime.now(timezone.utc).isoformat(), "history": []}
        value["models"].append(record)
        self._write(value)
        return record

    @_registry_locked
    def transition(self, model_id: str, state: ModelState, *, metrics: dict | None = None, decision: str | None = None) -> dict:
        value = self.read()
        record = next((item for item in value["models"] if item["model_id"] == model_id), None)
        if record is None:
            raise KeyError("Unknown model ID.")
        current = ModelState(record["state"])
        if state not in _TRANSITIONS[current]:
            raise ValueError(f"Invalid model lifecycle transition {current} -> {state}.")
        if state == ModelState.ACTIVE:
            if not decision or not metrics or not record.get("runtime_model"):
                raise ValueError("Activation requires a runtime model, approval decision, and evaluation metrics.")
            old_active = value.get("active_model_id")
            value["rollback_model_id"] = old_active
            value["active_model_id"] = model_id
            record["activated_at"] = datetime.now(timezone.utc).isoformat()
        if metrics is not None:
            record["metrics"] = metrics
        record["history"].append({"from": current.value, "to": state.value, "at": datetime.now(timezone.utc).isoformat(), "decision": decision})
        record["state"] = state.value
        self._write(value)
        return record

    @_registry_locked
    def rollback(self) -> str | None:
        value = self.read()
        previous = value.get("rollback_model_id")
        if not previous:
            return None
        target = next((item for item in value["models"] if item["model_id"] == previous and item["state"] in {"ACTIVE", "APPROVED"}), None)
        if target is None:
            return None
        current = next((item for item in value["models"] if item["model_id"] == value.get("active_model_id")), None)
        if current and current["state"] == ModelState.ACTIVE.value:
            current["state"] = ModelState.APPROVED.value
            current["history"].append({"from": "ACTIVE", "to": "APPROVED", "at": datetime.now(timezone.utc).isoformat(), "decision": "rollback"})
        prior_state = target["state"]
        target["state"] = ModelState.ACTIVE.value
        target["history"].append({"from": prior_state, "to": "ACTIVE", "at": datetime.now(timezone.utc).isoformat(), "decision": "rollback"})
        value["rollback_model_id"] = value.get("active_model_id")
        value["active_model_id"] = previous
        self._write(value)
        return previous


_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.I),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{20,})\b"),
]
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")


def redact_sensitive(text: str) -> str:
    result = text[:20000]
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub("[REDACTED_SECRET]", result)
    return _EMAIL.sub("[REDACTED_EMAIL]", result)


def validate_split_files(directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    schema_version = manifest.get("schema_version")
    if schema_version not in {"1.0", "2.0"} or not manifest.get("dataset_version"):
        raise ValueError("Dataset manifest schema or version is invalid.")
    ids: set[str] = set()
    counts = {}
    hashes = {}
    for split in ("train", "validation", "test"):
        path = directory / f"{split}.jsonl"
        raw = path.read_bytes()
        hashes[path.name] = hashlib.sha256(raw).hexdigest()
        rows = []
        for line in raw.decode("utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row.get("id"), str) or row["id"] in ids:
                raise ValueError(f"Missing or overlapping example ID in {split} split.")
            if row.get("split") != split:
                raise ValueError(f"Invalid example split in {split}.")
            provenance = row.get("provenance", {})
            if not provenance.get("origin") or not provenance.get("license"):
                raise ValueError(f"Example {row['id']} lacks provenance and license metadata.")
            if schema_version == "1.0":
                if provenance.get("origin") != "synthetic_hand_authored" or provenance.get("license") != manifest.get("example_license"):
                    raise ValueError("Version 1.0 records require matching synthetic provenance/license.")
                input_text, expected = row.get("text"), row.get("expected")
            else:
                if row.get("dataset_version") != manifest["dataset_version"] or row.get("schema_version") != "1.0":
                    raise ValueError("Engineering example schema or dataset version does not match the manifest.")
                if row.get("task_category") not in manifest.get("supported_categories", []):
                    raise ValueError("Unsupported engineering task category.")
                if row.get("review_status") not in {"SYNTHETIC_REVIEWED", "HUMAN_APPROVED"}:
                    raise ValueError("Unreviewed examples cannot enter the training split.")
                input_text, expected = row.get("input"), row.get("expected_output")
            if not isinstance(input_text, str) or not input_text.strip():
                raise ValueError(f"Example {row['id']} has no input text.")
            if not isinstance(expected, dict) or (schema_version == "1.0" and not isinstance(expected.get("parsed"), bool)):
                raise ValueError(f"Example {row['id']} lacks typed expected output.")
            ids.add(row["id"])
            rows.append(row)
        if not rows:
            raise ValueError(f"Dataset split {split} is empty.")
        counts[split] = len(rows)
    return {"dataset_version": manifest["dataset_version"], "splits": counts, "sha256": hashes, "examples": len(ids)}


def component_context(design: Any, component_id: str) -> dict:
    """Return bounded, canonical component facts only; never model-invented state."""
    if design.family == "electric_vehicle":
        from .automotive import vehicle_manifest
        manifest = vehicle_manifest(design)
        component = next((item for item in manifest["components"] if item["id"] == component_id), None)
        if component is None:
            raise KeyError("Unknown component ID.")
        parent = component.get("parent_id")
        return {"family": design.family, "revision": design.revision, "component": component,
                "parameters": design.requirements.model_dump(mode="json"), "parent_id": parent,
                "assumptions": design.assumptions[:12], "evidence": {k: v.evidence for k, v in design.requirements if hasattr(v, "evidence") and v.evidence}}
    if design.family == "spur_gear_pair":
        component = next((item for item in design.components if item.id == component_id), None)
        if component is None:
            raise KeyError("Unknown component ID.")
        return {"family": design.family, "revision": design.revision,
                "component": component.model_dump(mode="json"), "parameters": design.requirements.model_dump(mode="json"),
                "assumptions": design.assumptions[:12], "parent_id": "gear-pair",
                "evidence": {}}
    raise KeyError("Current project family is unsupported for component assistance.")


def validate_tool_proposal(value: dict) -> dict:
    """Model-suggested operations are allowlisted proposals, never execution."""
    allowed = {"refresh_project", "generate_component_mesh", "export_assembly", "export_report", "recalculate"}
    if set(value) - {"tool", "component_id", "expected_revision", "reason"}:
        raise ValueError("Tool proposal contains forbidden fields.")
    if value.get("tool") not in allowed:
        raise ValueError("Unsupported tool proposal.")
    if not isinstance(value.get("expected_revision"), int) or value["expected_revision"] < 1:
        raise ValueError("Tool proposal must bind to a positive project revision.")
    if not isinstance(value.get("reason"), str) or len(value["reason"]) > 500:
        raise ValueError("Tool proposal requires a short reason.")
    component_id = value.get("component_id")
    if component_id is not None and (not isinstance(component_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", component_id)):
        raise ValueError("Invalid component reference.")
    return {**value, "requires_user_confirmation": True, "executed": False}


def configured_runtime_model(registry: ModelRegistry, environment_model: str = "") -> tuple[str, str | None]:
    """Resolve the active registry model before using a local baseline setting."""
    try:
        state = registry.read()
    except (OSError, ValueError, json.JSONDecodeError):
        return environment_model.strip(), None
    active_id = state.get("active_model_id")
    if active_id:
        record = next((item for item in state["models"] if item.get("model_id") == active_id and item.get("state") == ModelState.ACTIVE.value), None)
        if record and record.get("runtime_model"):
            return record["runtime_model"], active_id
    return environment_model.strip(), None
