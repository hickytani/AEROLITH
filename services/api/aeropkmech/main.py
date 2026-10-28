from __future__ import annotations

import os
import html
import hashlib
import json
import uuid
import re
import math
from threading import RLock
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from io import BytesIO

from . import cad, store
from . import artifacts as artifact_store
from .assemblies import build_assembly_evidence
from .domain import Design, EditRequest, InterpretRequest
from .automotive import (COMPONENT_INFO, VEHICLE_DRAWING_VERSION, VEHICLE_EDITABLE_PARAMETERS, VEHICLE_GENERATOR_VERSION, VehicleDesign, VehicleGenerationRequest, VehicleParameterEditRequest, make_vehicle_design, propagate_vehicle_edits, vehicle_bom, vehicle_manifest, vehicle_verification, vehicle_component_solids, export_vehicle_drawing_pdf, export_vehicle_component_stl, export_vehicle_step, export_vehicle_stl)
from .engineering import calculation_details, derive, validate
from .drawings import GEAR_DRAWING_VERSION, gear_pair_reference_pdf
from .families import (
    IMPLEMENTED_FAMILIES,
    PLANNED_FAMILY_AREAS,
    FamilyInitializationRequest,
    GearExperimentRequest,
    UnsupportedDesignFamily,
    get_family,
    list_families,
)
from .intelligence import ParameterEditProposal, extract, propose_parameter_edit, propose_specification, assess_field_grounding, GroundingVerdict
from .model_platform import (
    ComponentAnswer, InferenceStatus, ModelRegistry, ModelState, ModelUnavailable, OllamaProvider,
    OllamaRequirementProvider, component_context, configured_runtime_model, redact_sensitive, validate_split_files, validate_tool_proposal,
)
from .verification import VerificationState, summarize

app = FastAPI(title="AeroPKmech API", version="0.2.0", description="Versioned educational spur gear design workflow")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"], allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["*"])
ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = Path(os.environ.get("AEROPKMECH_ARTIFACTS_DIR", ROOT / "artifacts"))
PUBLIC = ROOT / "public"
LEARNING = Path(os.environ.get("AEROPKMECH_LEARNING_DIR", ROOT / "data" / "learning"))
MODEL_REGISTRY = ModelRegistry(Path(os.environ.get("AEROPKMECH_MODEL_REGISTRY", ROOT / "data" / "models" / "registry.json")))
_LEARNING_LOCK = RLock()
THREE_VENDOR = ROOT / "node_modules" / "three"
if THREE_VENDOR.is_dir():
    app.mount("/vendor", StaticFiles(directory=THREE_VENDOR), name="three-vendor")


class ArtifactExecutionError(RuntimeError):
    pass


def require_current_revision(design):
    latest = store.load()
    if latest.revision != design.revision:
        raise HTTPException(status_code=409, detail=f"Design changed from revision {design.revision} to {latest.revision} during artifact generation.", headers={"X-Design-Revision":str(latest.revision)})


def response(design: Design | VehicleDesign, assembly_evidence=None) -> dict:
    family = get_family(design.family, design.schema_version)
    family.validate_state(design)
    verification = {key: item.model_dump(mode="json") if hasattr(item, "model_dump") else item for key, item in family.verify(design).items()}
    result = {**design.model_dump(mode="json"), "derived": family.calculate(design), "verification": verification,
              "assembly_verification": assembly_evidence if assembly_evidence is not None else build_assembly_evidence(design)}
    if design.family == "spur_gear_pair":
        hub_refs = ["hub_diameter_mm", "hub_length_mm"] if getattr(design.requirements, "hub_diameter_mm", None) is not None else []
        bore_refs = (["bore_diameter_mm"] if getattr(design.requirements, "bore_diameter_mm", None) is not None else []) + (["keyway_width_mm", "keyway_depth_mm"] if getattr(design.requirements, "keyway_width_mm", None) is not None else [])
        component_refs = {
            "pinion": ["pinion_teeth", "module_mm", "face_width_mm", "pressure_angle_deg"] + hub_refs + bore_refs,
            "gear": ["gear_teeth", "module_mm", "face_width_mm", "pressure_angle_deg"] + bore_refs,
            "gear-pair": ["input_torque_Nm", "input_speed_rpm", "gear_ratio"],
        }
        values = {**design.requirements.model_dump(exclude_none=True), "pinion_teeth": design.components[0].teeth, "gear_teeth": design.components[1].teeth}
        units = {"pinion_teeth":"teeth","gear_teeth":"teeth","gear_ratio":"ratio","module_mm":"mm","face_width_mm":"mm","pressure_angle_deg":"deg","input_torque_Nm":"N·m","input_speed_rpm":"rpm","hub_diameter_mm":"mm","hub_length_mm":"mm","bore_diameter_mm":"mm","keyway_width_mm":"mm","keyway_depth_mm":"mm"}
        trace = {name:{"canonical_target":f"requirements.{name}" if name not in {"pinion_teeth","gear_teeth"} else f"components.{name.removesuffix('_teeth')}.teeth","value":value,"unit":units.get(name, "mm"),"source":design.requirement_sources.get(name,"derived" if name=="gear_ratio" else "assumed"),"evidence":design.requirement_evidence.get(name),"quantity":design.parameter_quantities[name].model_dump(mode="json")} for name,value in values.items() if name in design.parameter_quantities}
        for item in trace.values():
            evidence=item["evidence"]
            if evidence and design.source_prompt:
                offset=design.source_prompt.find(evidence)
                if offset>=0: item["source_span"]={"start":offset,"end":offset+len(evidence),"text":evidence}
        return {**result, "requirement_traceability":{"source_prompt":design.source_prompt,"components":{key:refs for key,refs in component_refs.items()},"parameters":trace}, "calculations": calculation_details(design), "validation": validate(design)}
    result["editable_parameters"]={name:{**metadata,"value":getattr(design.requirements,name).value,"source":getattr(design.requirements,name).source,"evidence":getattr(design.requirements,name).evidence} for name,metadata in VEHICLE_EDITABLE_PARAMETERS.items()}
    return {**result, "calculations":{"provenance":{"method_version":VEHICLE_GENERATOR_VERSION,"design_revision":design.revision},"results":[]}, "validation":{"state":"PARTIAL","issues":["Conceptual packaging geometry only; range and safety remain unresolved."]}}


def save_candidate_at_revision(candidate: Design | VehicleDesign, expected_revision: int) -> None:
    """Commit only if the canonical snapshot used to build this candidate is current."""
    try:
        store.save_if_revision(candidate, expected_revision)
    except store.ProjectRevisionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Project revision advanced from {exc.expected_revision} to {exc.current_revision}. Reload and review before committing.",
            headers={"X-Design-Revision": str(exc.current_revision)},
        ) from exc


@app.exception_handler(store.ProjectStateError)
async def project_state_error(_, exc: store.ProjectStateError):
    return JSONResponse(status_code=503, content={"detail": str(exc), "verification": {"state": VerificationState.EXECUTION_ERROR.value}})


@app.exception_handler(store.ProjectPersistenceError)
async def project_persistence_error(_, exc: store.ProjectPersistenceError):
    return JSONResponse(status_code=500, content={"detail": str(exc), "verification": {"state": VerificationState.EXECUTION_ERROR.value}})


@app.exception_handler(ArtifactExecutionError)
async def artifact_execution_error(_, exc: ArtifactExecutionError):
    return JSONResponse(status_code=500, content={"detail": str(exc), "verification": {"state": VerificationState.EXECUTION_ERROR.value}})


@app.get("/api/v1/health")
def health():
    return {"ok": True, "service": "AeroPKmech API", "kernel": "CadQuery / Open CASCADE", "state": "local-file"}


@app.get("/api/v1/model/status")
async def model_status():
    model_name, model_id = configured_runtime_model(MODEL_REGISTRY, os.environ.get("AEROPKMECH_OLLAMA_MODEL", ""))
    if not model_name:
        return {"provider": "deterministic-fallback", "configured": False, "available": False,
                "status": "DISABLED", "model_id": None, "note": "No local model is selected. Deterministic workflows remain active."}
    try:
        provider = OllamaProvider(model_name, os.environ.get("AEROPKMECH_OLLAMA_URL", "http://127.0.0.1:11434"))
    except ValueError:
        return {"provider": "ollama-local", "model": model_name, "model_id": model_id, "configured": True,
                "available": False, "service_reachable": False, "model_installed": False,
                "status": "INVALID_CONFIGURATION", "endpoint": "loopback-only"}
    probe = await provider.probe()
    return {"provider": "ollama-local", "model": model_name, "model_id": model_id, "configured": True,
            "available": probe["service_reachable"] and probe["model_installed"], **probe,
            "endpoint": "loopback-only", "inference_tested": False}


class ComponentQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    question: str = Field(min_length=3, max_length=2000)


@app.post("/api/v1/components/explain")
async def explain_component(request: ComponentQuestion):
    design = store.load()
    try:
        context = component_context(design, request.component_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    deterministic = ComponentAnswer(
        answer=(f"{context['component'].get('name', context['component'].get('id'))} is a {context['component'].get('role', context['component'].get('family', 'component'))} in revision {design.revision}. "
                "The values below come from the committed project; conceptual envelope geometry does not establish structural or safety performance."),
        evidence=[f"Current family: {design.family}", f"Canonical project revision: {design.revision}"],
        limitations=["This response is grounded in stored project metadata; no independent strength, safety, or performance analysis is implied."],
    )
    model_name, model_id = configured_runtime_model(MODEL_REGISTRY, os.environ.get("AEROPKMECH_OLLAMA_MODEL", ""))
    if not model_name:
        return {**deterministic.model_dump(), "provider": "deterministic-context", "model_available": False, "model_status": "DISABLED", "inference_succeeded": False, "revision": design.revision}
    try:
        provider = OllamaProvider(model_name, os.environ.get("AEROPKMECH_OLLAMA_URL", "http://127.0.0.1:11434"))
    except ValueError:
        return {**deterministic.model_dump(), "provider": "deterministic-context", "model_available": False, "model_status": "INVALID_CONFIGURATION", "inference_succeeded": False, "revision": design.revision}
    probe = await provider.probe()
    if not probe["service_reachable"] or not probe["model_installed"]:
        return {**deterministic.model_dump(), "provider": "deterministic-context", "model_available": probe["model_installed"], "model_status": probe["status"], "inference_succeeded": False, "revision": design.revision}
    system = ("Answer a question about the selected engineering component using only supplied JSON context. "
              "Do not infer ratings, materials, safety, achieved range, or missing specifications. Return JSON with answer, evidence, limitations. "
              "The result is advisory and cannot change the design.")
    prompt = json.dumps({"question": request.question, "context": context}, ensure_ascii=False)[:12000]
    try:
        raw = await provider.generate(prompt, system=system)
        answer = ComponentAnswer.model_validate_json(raw)
        current = store.load()
        if current.revision != design.revision:
            raise HTTPException(status_code=409, detail="Project changed while the component explanation was being generated.", headers={"X-Design-Revision": str(current.revision)})
        return {**answer.model_dump(), "provider": "ollama-local", "model": model_name, "model_id": model_id, "model_available": True, "model_status": "INFERENCE_SUCCEEDED", "inference_succeeded": True, "revision": design.revision}
    except ModelUnavailable as exc:
        return {**deterministic.model_dump(), "provider": "deterministic-context", "model_available": True, "revision": design.revision, "model_status": exc.code, "inference_succeeded": False}
    except (ValueError, json.JSONDecodeError):
        return {**deterministic.model_dump(), "provider": "deterministic-context", "model_available": True, "revision": design.revision, "model_status": "INVALID_MODEL_OUTPUT", "inference_succeeded": False}


class TraceCapture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    opt_in: Literal[True]
    input_text: str = Field(min_length=1, max_length=20000)
    structured_output: dict = Field(default_factory=dict)
    tool_results: list[dict] = Field(default_factory=list, max_length=50)
    correction: str | None = Field(default=None, max_length=10000)
    final_revision: int | None = Field(default=None, ge=1)


class ModelCandidateMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str = Field(min_length=1, max_length=120)
    runtime_model: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    base_model: str = Field(min_length=1, max_length=200)
    base_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    dataset_version: str = Field(min_length=1, max_length=100)
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adapter_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_suite: str = Field(min_length=1, max_length=100)
    metrics: dict
    environment: dict


class ModelTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["EVALUATED", "APPROVED", "REJECTED", "ACTIVE"]
    metrics: dict | None = None
    decision: str | None = Field(default=None, max_length=1000)


@app.post("/api/v1/learning/traces")
def capture_learning_trace(request: TraceCapture):
    if os.environ.get("AEROPKMECH_ENABLE_TRAINING_CAPTURE", "false").lower() != "true":
        raise HTTPException(status_code=403, detail="Training data capture is disabled. Enable it explicitly in local configuration first.")
    trace_id = f"trace-{uuid.uuid4().hex}"
    record = {"id": trace_id, "captured_at": datetime.now(timezone.utc).isoformat(),
              "origin": "opt_in_execution_trace", "review_status": "UNREVIEWED",
              "input_text": redact_sensitive(request.input_text),
              "structured_output": json.loads(redact_sensitive(json.dumps(request.structured_output, ensure_ascii=False))),
              "tool_results": json.loads(redact_sensitive(json.dumps(request.tool_results, ensure_ascii=False))),
              "correction": redact_sensitive(request.correction) if request.correction else None,
              "final_revision": request.final_revision, "curation": "raw_only"}
    directory = LEARNING / "raw-traces"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{trace_id}.json"
    with _LEARNING_LOCK:
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"id": trace_id, "stored": True, "review_status": "UNREVIEWED", "curation": "raw_only"}


@app.delete("/api/v1/learning/traces/{trace_id}")
def delete_learning_trace(trace_id: str):
    if not re.fullmatch(r"trace-[0-9a-f]{32}", trace_id):
        raise HTTPException(status_code=404, detail="Trace not found.")
    path = LEARNING / "raw-traces" / f"{trace_id}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Trace not found.")
    quarantine = LEARNING / "quarantine"
    quarantine.mkdir(parents=True, exist_ok=True)
    with _LEARNING_LOCK:
        os.replace(path, quarantine / f"{trace_id}.json")
    return {"id": trace_id, "deleted": True, "quarantined": True}


class TraceCuration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    human_reviewed: Literal[True]
    reviewer: str = Field(min_length=1, max_length=100)
    source_license: str = Field(min_length=1, max_length=200)
    task_category: Literal["requirement_extraction", "constraint_interpretation", "assembly_planning", "engineering_tool_use", "component_understanding", "change_impact", "failure_handling", "engineering_explanation"]
    expected_output: dict


class TraceReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["APPROVED", "REJECTED"]
    reviewer: str = Field(min_length=1, max_length=100)
    review_note: str = Field(min_length=1, max_length=2000)


@app.post("/api/v1/learning/traces/{trace_id}/review")
def review_learning_trace(trace_id: str, request: TraceReview):
    if not re.fullmatch(r"trace-[0-9a-f]{32}", trace_id):
        raise HTTPException(status_code=404, detail="Trace not found.")
    path = LEARNING / "raw-traces" / f"{trace_id}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Trace not found.")
    with _LEARNING_LOCK:
        record = json.loads(path.read_text(encoding="utf-8"))
        record["review_status"] = request.decision
        record["review"] = {"reviewer": request.reviewer, "note": redact_sensitive(request.review_note), "reviewed_at": datetime.now(timezone.utc).isoformat()}
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"id": trace_id, "review_status": request.decision}


@app.post("/api/v1/learning/traces/{trace_id}/curate")
def curate_learning_trace(trace_id: str, request: TraceCuration):
    if not re.fullmatch(r"trace-[0-9a-f]{32}", trace_id):
        raise HTTPException(status_code=404, detail="Trace not found.")
    raw_path = LEARNING / "raw-traces" / f"{trace_id}.json"
    if not raw_path.is_file():
        raise HTTPException(status_code=404, detail="Trace not found.")
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    if raw.get("review_status") != "APPROVED":
        raise HTTPException(status_code=409, detail="Only explicitly approved traces can be curated.")
    example = {"id": trace_id, "task_category": request.task_category, "input": raw["input_text"],
               "context": {"tool_results": raw["tool_results"], "final_revision": raw["final_revision"]},
               "expected_output": request.expected_output, "schema_version": "1.0",
               "provenance": {"origin": "reviewed_execution_trace", "reviewer": request.reviewer,
                              "source_license": request.source_license, "review_status": "APPROVED"},
               "dataset_version": "engineering-v2.0.0", "validation": {"secrets_redacted": True, "human_reviewed": True}}
    target = LEARNING / "curated" / "engineering-v2.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with _LEARNING_LOCK:
        existing = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
        if any(json.loads(line).get("id") == trace_id for line in existing if line.strip()):
            raise HTTPException(status_code=409, detail="Trace is already in the curated dataset.")
        with target.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(example, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    return {"id": trace_id, "curated": True, "dataset_version": "engineering-v2", "review_status": "APPROVED"}


@app.get("/api/v1/learning/dataset/status")
def learning_dataset_status(version: Literal["1.0.0", "engineering-v2.0.0"] = "1.0.0"):
    try:
        directory = LEARNING if version == "1.0.0" else LEARNING / "engineering-v2"
        return validate_split_files(directory)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"Dataset validation failed: {exc}") from exc


@app.post("/api/v1/engineering/tools/validate-proposal")
def validate_engineering_tool_proposal(payload: dict):
    try:
        return validate_tool_proposal(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/models/registry")
def get_model_registry():
    try:
        return MODEL_REGISTRY.read()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail=f"Model registry is unavailable: {exc}") from exc


@app.post("/api/v1/models/registry/candidates", status_code=201)
def register_model_candidate(request: ModelCandidateMetadata):
    try:
        return MODEL_REGISTRY.register(request.model_dump())
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.patch("/api/v1/models/registry/{model_id}")
def transition_model_candidate(model_id: str, request: ModelTransitionRequest):
    try:
        return MODEL_REGISTRY.transition(model_id, ModelState(request.state), metrics=request.metrics, decision=request.decision)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/models/registry/rollback")
def rollback_active_model():
    try:
        model_id = MODEL_REGISTRY.rollback()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail=f"Model registry is unavailable: {exc}") from exc
    if model_id is None:
        raise HTTPException(status_code=409, detail="No approved rollback model is recorded.")
    return {"active_model_id": model_id, "rolled_back": True}


@app.get("/api/v1/platform/openapi", include_in_schema=False)
def platform_openapi():
    """Live API contract used by the local developer portal."""
    return app.openapi()


@app.get("/api/v1/design-families")
def design_families():
    return {
        "families": [item.__dict__ for item in list_families()],
        "planned_areas": list(PLANNED_FAMILY_AREAS),
        "persistence": "single local project; initialization replaces the active state while retaining its revision history",
    }


@app.get("/api/v1/project")
def get_project():
    return response(store.load())


@app.post("/api/v1/project/initialize")
def initialize_project(request: FamilyInitializationRequest):
    try:
        family = get_family(request.family_id, request.schema_version)
    except UnsupportedDesignFamily as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    current = store.load()
    candidate = family.default_design()
    candidate.id = f"local-{uuid.uuid4().hex[:12]}"
    candidate.parameter_records = {}
    candidate.revision = current.revision + 1
    candidate.history = [*current.history, {"revision": current.revision, "changed_at": current.updated_at, "design": current.model_dump(mode="json", exclude={"history"})}]
    candidate.updated_at = datetime.now(timezone.utc).isoformat()
    if candidate.family == "electric_vehicle":
        from .automotive import VehicleDesign
        candidate = VehicleDesign.model_validate(candidate.model_dump(mode="json"))
    else:
        candidate = Design.model_validate(candidate.model_dump(mode="json"))
    family.validate_state(candidate)
    store.save(candidate)
    return response(candidate)


@app.post("/api/v1/project/demo")
def restore_demo_project():
    current = store.load()
    candidate = store.default_design()
    candidate.parameter_records = {}
    candidate.revision = current.revision + 1
    candidate.history = [*current.history, {"revision": current.revision, "changed_at": current.updated_at, "design": current.model_dump(mode="json", exclude={"history"})}]
    candidate.updated_at = datetime.now(timezone.utc).isoformat()
    candidate = Design.model_validate(candidate.model_dump(mode="json"))
    store.save(candidate)
    return response(candidate)


@app.post("/api/v1/learn/spur-gear/experiment")
def gear_experiment(parameters: GearExperimentRequest):
    """Evaluate lesson inputs with the real deterministic gear equations, without persistence."""
    current = store.load()
    design = IMPLEMENTED_FAMILIES["spur_gear_pair"].default_design()
    values = parameters.model_dump()
    design.components[0].teeth = values["pinion_teeth"]
    design.components[1].teeth = values["gear_teeth"]
    for key in ("module_mm", "face_width_mm", "pressure_angle_deg", "input_torque_Nm", "input_speed_rpm"):
        setattr(design.requirements, key, values[key])
    design.requirements.gear_ratio = values["gear_teeth"] / values["pinion_teeth"]
    design.revision = current.revision
    design.parameter_quantities = {}
    design.parameter_records = {}
    design = Design.model_validate(design.model_dump(mode="json"))
    details = calculation_details(design)
    details["provenance"].update({"design_revision": None, "source_revision": current.revision, "context": "uncommitted learning experiment"})
    for item in details["results"]:
        item["design_revision"] = None
        item["source_revision"] = current.revision
    return {"parameters": values, "derived": derive(design), "calculations": details}


@app.patch("/api/v1/project")
def edit_project(edit: EditRequest):
    current = store.load()
    if current.family != "spur_gear_pair":
        raise HTTPException(status_code=422, detail="This project belongs to the electric_vehicle family. Submit reviewed EV parameters to /api/v1/project/vehicle/generate.")
    values = edit.model_dump(exclude_none=True)
    expected_revision = values.pop("expected_revision", None)
    source_prompt = values.pop("source_prompt", None)
    requirement_sources = values.pop("requirement_sources", {})
    requirement_evidence = values.pop("requirement_evidence", {})
    changed_names = set(values)
    if expected_revision is not None and expected_revision != current.revision:
        raise HTTPException(
            status_code=409,
            detail=f"Project revision advanced from {expected_revision} to {current.revision}. Reload and review the current design before applying edits.",
            headers={"X-Design-Revision": str(current.revision)},
        )
    candidate = current.model_copy(deep=True)
    candidate.history.append({"revision": current.revision, "changed_at": current.updated_at, "design": current.model_dump(mode="json", exclude={"history"})})
    if "pinion_teeth" in values:
        candidate.components[0].teeth = values.pop("pinion_teeth")
    if "gear_teeth" in values:
        candidate.components[1].teeth = values.pop("gear_teeth")
    for key, value in values.items():
        setattr(candidate.requirements, key, value)
    angle_assumption = (
        "Ordinary unshifted external spur gears; sampled involute flanks at "
        f"{candidate.requirements.pressure_angle_deg:g}° pressure angle."
    )
    candidate.assumptions = [angle_assumption, *(
        item for item in candidate.assumptions
        if not item.startswith("Ordinary unshifted external spur gears; sampled involute flanks at ")
    )]
    candidate.requirements.gear_ratio = candidate.components[1].teeth / candidate.components[0].teeth
    if source_prompt is not None:
        candidate.source_prompt = source_prompt
        candidate.requirement_sources = dict(requirement_sources)
        candidate.requirement_evidence = dict(requirement_evidence)
    else:
        candidate.requirement_sources.update(requirement_sources)
        candidate.requirement_evidence.update(requirement_evidence)
    for name in changed_names:
        if name not in requirement_sources:
            candidate.requirement_sources[name] = "user-provided"
        if name not in requirement_evidence:
            candidate.requirement_evidence.pop(name, None)
    if changed_names.intersection({"pinion_teeth", "gear_teeth"}):
        candidate.requirement_sources["gear_ratio"] = "derived"
        candidate.requirement_evidence.pop("gear_ratio", None)
    candidate.revision += 1
    candidate.updated_at = datetime.now(timezone.utc).isoformat()
    # Canonical numeric fields remain API-compatible; rebuild their additive
    # versioned quantity envelopes for this candidate revision.
    candidate.parameter_quantities = {}
    candidate.parameter_records = {}
    # Validate the complete candidate (including cross-field invariants) before persistence.
    try:
        candidate = Design.model_validate(candidate.model_dump(mode="json"))
        # Generate and verify the full candidate geometry before persistence. If
        # profile construction or a geometry-backed check fails, the old revision
        # and its artifacts remain canonical.
        assembly_evidence = build_assembly_evidence(candidate)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    save_candidate_at_revision(candidate, current.revision)
    return response(candidate, assembly_evidence)


@app.post("/api/v1/project/interpret")
async def interpret(request: InterpretRequest):
    model_name, _ = configured_runtime_model(MODEL_REGISTRY, os.environ.get("AEROPKMECH_OLLAMA_MODEL", ""))
    use_model = os.environ.get("AEROPKMECH_ENABLE_MODEL_EXTRACTION", "false").lower() == "true"
    extracted_obj = None
    if model_name and use_model:
        provider = OllamaRequirementProvider(model_name, os.environ.get("AEROPKMECH_OLLAMA_URL", "http://127.0.0.1:11434"))
        try:
            result = await extract(request.text, provider)
            extracted_obj = result
            result_dict = result.model_dump(mode="json")
            result_dict["model_status"] = "PROPOSED_REQUIRES_REVIEW" if result.inference_path == "local_slm" else "FALLBACK_TO_DETERMINISTIC"
            result_dict["inference_succeeded"] = result.inference_path == "local_slm"
            result_dict["inference_path"] = result.inference_path
        except ModelUnavailable as exc:
            extracted_obj = await extract(request.text)
            fallback = extracted_obj.model_dump(mode="json")
            fallback["model_status"] = exc.code
            fallback["inference_succeeded"] = False
            fallback["inference_path"] = "deterministic_fallback"
            result_dict = fallback
        except ValueError:
            extracted_obj = await extract(request.text)
            fallback = extracted_obj.model_dump(mode="json")
            fallback["model_status"] = "INVALID_MODEL_OUTPUT"
            fallback["inference_succeeded"] = False
            fallback["inference_path"] = "deterministic_fallback"
            result_dict = fallback
    else:
        result = await extract(request.text)
        extracted_obj = result
        result_dict = result.model_dump(mode="json")
        result_dict["inference_path"] = "deterministic"

    proposal_data = result_dict.get("proposal", {})
    grounding = {}
    for field, val in proposal_data.items():
        verdict = assess_field_grounding(field, val, request.text, extraction=extracted_obj)
        grounding[field] = verdict.as_dict()
    result_dict["field_grounding"] = grounding
    return result_dict


class ChangeImpactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    changed_parameters: list[str] = Field(min_length=1, max_length=30)


@app.post("/api/v1/project/change-impact")
def project_change_impact(request: ChangeImpactRequest):
    design = store.load()
    if request.expected_revision != design.revision:
        raise HTTPException(status_code=409, detail="Project revision changed; reload before previewing change impact.", headers={"X-Design-Revision": str(design.revision)})
    if design.family == "electric_vehicle":
        allowed = set(type(design.requirements).model_fields) - {"propulsion_layout"}
        affected = ["vehicle component geometry", "assembly STEP/STL", "layout drawing PDF", "manifest JSON", "BOM JSON", "calculations and dimensional checks"]
    else:
        allowed = set(type(design.requirements).model_fields) | {"pinion_teeth", "gear_teeth"}
        affected = ["affected gear component meshes", "assembly STEP/STL", "engineering report", "kinematic calculations", "verification summary"]
    unknown = sorted(set(request.changed_parameters) - allowed)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unsupported parameter(s) for {design.family}: {', '.join(unknown)}")
    try:
        artifacts = artifact_store.list_artifacts(ARTIFACTS, design)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Artifact state is unavailable for change-impact analysis.") from exc
    return {"family": design.family, "source_revision": design.revision, "changed_parameters": sorted(set(request.changed_parameters)),
            "affected_outputs": affected, "currently_stale_artifacts": [item["artifact_id"] for item in artifacts if item["stale"]],
            "outputs_will_become_stale_after_commit": True, "design_mutated": False,
            "note": "Dependency mapping is conservative and family-level; each listed output must be regenerated or recalculated after the reviewed edit."}


class ProposeEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str | None = Field(default=None, max_length=2000)
    prompt: str | None = Field(default=None, max_length=2000)
    expected_revision: int | None = None

    @model_validator(mode="after")
    def resolve_text(self):
        query = (self.text or self.prompt or "").strip()
        if not query:
            raise ValueError("Edit request must provide a non-empty text or prompt.")
        if self.text is None:
            self.text = query
        return self


@app.post("/api/v1/project/propose-edit")
def propose_project_edit(request: ProposeEditRequest):
    """Parse a natural-language parameter edit into a reviewable, revision-safe proposal."""
    design = store.load()
    if request.expected_revision is not None and request.expected_revision != design.revision:
        raise HTTPException(
            status_code=409,
            detail=f"Project revision advanced from {request.expected_revision} to {design.revision}. Reload and review before proposing edits.",
            headers={"X-Design-Revision": str(design.revision)},
        )
    proposal = propose_parameter_edit(request.text, design)
    return proposal.model_dump(mode="json")


@app.post("/api/v1/specifications/propose")
def propose_project_specification(request: InterpretRequest):
    """Return a schema-validated, uncommitted prompt-to-system proposal."""
    return propose_specification(request.text).model_dump(mode="json")


@app.post("/api/v1/project/vehicle/generate")
def generate_vehicle_project(request: VehicleGenerationRequest):
    """Commit a reviewed EV envelope spec through the shared project file/revision history."""
    current = store.load()
    if request.expected_revision != current.revision:
        raise HTTPException(status_code=409, detail=f"Project revision advanced from {request.expected_revision} to {current.revision}.", headers={"X-Design-Revision": str(current.revision)})
    history = [*current.history, {"revision":current.revision,"changed_at":current.updated_at,"design":current.model_dump(mode="json", exclude={"history"})}]
    try:
        candidate = make_vehicle_design(request, current.revision + 1, history)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    candidate.id = current.id
    candidate.parameter_records = {}
    if candidate.family == "electric_vehicle":
        candidate = VehicleDesign.model_validate(candidate.model_dump(mode="json"))
    save_candidate_at_revision(candidate, current.revision)
    return response(candidate)


@app.patch("/api/v1/project/vehicle")
def edit_vehicle_project(edit: VehicleParameterEditRequest):
    """Regenerate and validate an allowlisted EV geometry edit before revision commit."""
    current=store.load()
    if current.family!="electric_vehicle":
        raise HTTPException(status_code=422,detail="EV parameter edits require the electric_vehicle family.")
    if edit.expected_revision!=current.revision:
        raise HTTPException(status_code=409,detail=f"Project revision advanced from {edit.expected_revision} to {current.revision}. Reload and review before editing.",headers={"X-Design-Revision":str(current.revision)})
    changes=edit.model_dump(exclude={"expected_revision"},exclude_none=True)
    try:
        candidate,propagated=propagate_vehicle_edits(current,changes)
        family=IMPLEMENTED_FAMILIES["electric_vehicle"]
        family.validate_state(candidate)
        solids=vehicle_component_solids(candidate)
        expected_ids=set(COMPONENT_INFO)
        if set(solids)!=expected_ids or len(solids)!=len(expected_ids):
            raise ValueError("Regenerated CAD component identities do not match the EV assembly contract.")
        if any(not solid.val().isValid() or not math.isfinite(solid.val().Volume()) or solid.val().Volume()<=0 for solid in solids.values()):
            raise ValueError("Regenerated CAD contains an invalid or zero-volume solid.")
        checks=vehicle_verification(candidate)
        required_checks=("schema_validation","component_geometry","wheel_axle_placement","frame_dimensions","overall_envelope_containment")
        failed=[name for name in required_checks if checks[name].state.value!="PASSED"]
        if failed:
            raise ValueError("Generated candidate failed required checks: "+", ".join(failed))
    except (ValueError,ValidationError) as exc:
        raise HTTPException(status_code=422,detail=f"EV edit rejected; canonical revision {current.revision} was preserved. {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500,detail="EV geometry regeneration failed; canonical project was not changed.",headers={"X-Verification-State":"EXECUTION_ERROR"}) from exc
    previous_artifacts=artifact_store.list_artifacts(ARTIFACTS,current)
    try:
        store.save_if_revision(candidate,current.revision)
    except store.ProjectRevisionConflict as exc:
        raise HTTPException(status_code=409,detail=str(exc),headers={"X-Design-Revision":str(exc.current_revision)}) from exc
    result=response(candidate)
    result["edit_result"]={
        "changed_parameters":list(changes),
        "propagated_parameters":propagated,
        "regenerated_components":sorted(solids),
        "artifacts_regenerated":[],
        "artifacts_stale":[item["artifact_id"] for item in previous_artifacts],
        "artifact_note":"CAD solids were regenerated and validated before commit. Export files are generated on request; this edit did not publish artifact files.",
    }
    return result


@app.get("/api/v1/export/stl")
def export_stl():
    design = store.load()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    temporary = ARTIFACTS / f".generating-{uuid.uuid4().hex}.stl"
    try:
        if design.family == "electric_vehicle":
            export_vehicle_stl(design, temporary)
            generator_version = VEHICLE_GENERATOR_VERSION
        else:
            cad.export_stl(design, temporary)
            generator_version = cad.GENERATOR_VERSION
        require_current_revision(design)
        path, metadata = artifact_store.publish(temporary.read_bytes(), ARTIFACTS, design, "assembly", "stl", generator_version)
    except HTTPException:
        raise
    except Exception as exc:
        raise ArtifactExecutionError(f"CadQuery STL export failed: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return FileResponse(path, media_type="model/stl", filename=path.name, headers=artifact_headers(metadata, design.revision))


@app.get("/api/v1/export/step")
def export_step():
    design = store.load()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    temporary = ARTIFACTS / f".generating-{uuid.uuid4().hex}.step"
    try:
        if design.family == "electric_vehicle":
            export_vehicle_step(design, temporary)
            generator_version = VEHICLE_GENERATOR_VERSION
        else:
            cad.export_step(design, temporary)
            generator_version = cad.GENERATOR_VERSION
        require_current_revision(design)
        path, metadata = artifact_store.publish(temporary.read_bytes(), ARTIFACTS, design, "assembly", "step", generator_version)
    except HTTPException:
        raise
    except Exception as exc:
        raise ArtifactExecutionError(f"CadQuery STEP export failed: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return FileResponse(path, media_type="model/step", filename=path.name, headers=artifact_headers(metadata, design.revision))


@app.get("/api/v1/geometry/{component_id}.stl")
def component_geometry(component_id: str, revision: int | None = Query(default=None, ge=1)):
    design = store.load()
    if design.family == "spur_gear_pair" and component_id not in {"pinion", "gear"}:
        raise HTTPException(status_code=404, detail=f"Unknown spur-gear component '{component_id}'.")
    if design.family == "electric_vehicle" and component_id not in {item["id"] for item in vehicle_manifest(design)["components"]}:
        raise HTTPException(status_code=404, detail=f"Unknown vehicle component '{component_id}'.")
    if revision is not None and revision != design.revision:
        raise HTTPException(
            status_code=409,
            detail=f"Requested geometry revision {revision} is not current; project revision is {design.revision}.",
            headers={"X-Design-Revision": str(design.revision)},
        )
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    temporary = ARTIFACTS / f".generating-{uuid.uuid4().hex}.stl"
    try:
        if design.family == "electric_vehicle":
            export_vehicle_component_stl(design, component_id, temporary)
        else:
            cad.export_component_stl(design, component_id, temporary)
        latest = store.load()
        if latest.revision != design.revision:
            raise HTTPException(
                status_code=409,
                detail=f"Design changed from revision {design.revision} to {latest.revision} while geometry was generated.",
                headers={"X-Design-Revision": str(latest.revision)},
            )
        generator_version = VEHICLE_GENERATOR_VERSION if design.family == "electric_vehicle" else cad.GENERATOR_VERSION
        path, metadata = artifact_store.publish(temporary.read_bytes(), ARTIFACTS, design, component_id, "stl", generator_version)
    except HTTPException:
        raise
    except Exception as exc:
        raise ArtifactExecutionError(f"CadQuery component tessellation failed for {component_id}: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return FileResponse(
        path,
        media_type="model/stl",
        filename=path.name,
        headers={
            **artifact_headers(metadata, design.revision),
            "Cache-Control": "no-store",
            "X-Geometry-Component-ID": component_id,
            "X-Geometry-Revision": str(design.revision),
            "X-Geometry-Units": "mm",
            "X-Geometry-Format": "stl",
        },
    )


def publish_vehicle_json_artifact(design: VehicleDesign, kind: str, payload: dict):
    require_current_revision(design)
    data = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    path, metadata = artifact_store.publish(data, ARTIFACTS, design, kind, "json", VEHICLE_GENERATOR_VERSION)
    return FileResponse(path, media_type="application/json", filename=path.name, headers=artifact_headers(metadata, design.revision))


@app.get("/api/v1/vehicle/manifest.json")
def vehicle_manifest_export():
    design = store.load()
    if design.family != "electric_vehicle": raise HTTPException(status_code=409, detail="Current project is not an electric vehicle.")
    return publish_vehicle_json_artifact(design, "manifest", vehicle_manifest(design))


@app.get("/api/v1/vehicle/bom.json")
def vehicle_bom_export():
    design = store.load()
    if design.family != "electric_vehicle": raise HTTPException(status_code=409, detail="Current project is not an electric vehicle.")
    return publish_vehicle_json_artifact(design, "bom", vehicle_bom(design))


@app.get("/api/v1/vehicle/layout.pdf")
def vehicle_layout_export():
    design = store.load()
    if design.family != "electric_vehicle": raise HTTPException(status_code=409, detail="Current project is not an electric vehicle.")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    temporary = ARTIFACTS / f".generating-{uuid.uuid4().hex}.pdf"
    try:
        export_vehicle_drawing_pdf(design, temporary)
        require_current_revision(design)
        path, metadata = artifact_store.publish(temporary.read_bytes(), ARTIFACTS, design, "layout-drawing", "pdf", VEHICLE_DRAWING_VERSION)
    except HTTPException:
        raise
    except Exception as exc:
        raise ArtifactExecutionError(f"Vehicle layout drawing failed: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return FileResponse(path, media_type="application/pdf", filename=path.name, headers=artifact_headers(metadata, design.revision))


@app.get("/api/v1/gear/layout.pdf")
def gear_layout_export():
    design = store.load()
    if design.family != "spur_gear_pair":
        raise HTTPException(status_code=409, detail="The gear reference drawing is only available for a spur_gear_pair project.")
    try:
        payload = gear_pair_reference_pdf(design)
        require_current_revision(design)
        path, metadata = artifact_store.publish(payload, ARTIFACTS, design, "gear-reference-drawing", "pdf", GEAR_DRAWING_VERSION)
    except HTTPException:
        raise
    except Exception as exc:
        raise ArtifactExecutionError("Gear reference drawing generation failed.") from exc
    return FileResponse(path, media_type="application/pdf", filename=path.name, headers=artifact_headers(metadata, design.revision))


@app.get("/api/v1/report", response_class=HTMLResponse)
def report():
    design = store.load()
    if design.family == "electric_vehicle":
        document = f"<!doctype html><meta charset='utf-8'><title>EV conceptual geometry R{design.revision}</title><h1>Concept EV packaging note</h1><p>Revision {design.revision} · {design.id} · conceptual only</p><h2>Parameters and provenance</h2><pre>{html.escape(design.requirements.model_dump_json(indent=2))}</pre><h2>Assembly manifest</h2><pre>{html.escape(json.dumps(vehicle_manifest(design),indent=2))}</pre><h2>Limits</h2><p>Range target is not calculated. No mass, structural, crash, thermal, regulatory, safety, or manufacturing verification is provided.</p>"
        path, metadata = artifact_store.publish(document.encode("utf-8"), ARTIFACTS, design, "report", "html", VEHICLE_GENERATOR_VERSION)
        return FileResponse(path,media_type="text/html",headers=artifact_headers(metadata,design.revision))
    derived = derive(design)
    rows = "".join(f"<tr><td>{key}</td><td>{value:.3f}</td></tr>" for key, value in derived.items() if isinstance(value, (int, float)))
    assumptions = "".join(f"<li>{html.escape(item)}</li>" for item in design.assumptions)
    verification = "".join(
        f"<li><strong>{html.escape(key)}: {item.state.value}</strong> — {html.escape(item.summary)}"
        + ("<ul>" + "".join(f"<li>{html.escape(evidence)}</li>" for evidence in item.evidence) + "</ul>" if item.evidence else "")
        + "</li>"
        for key, item in summarize(design).items()
    )
    document = f"""<!doctype html><meta charset="utf-8"><title>AeroPKmech report R{design.revision}</title>
    <style>body{{font:15px system-ui;max-width:900px;margin:48px auto;color:#13283a}}h1{{font-size:32px}}table{{border-collapse:collapse;width:100%}}td{{padding:10px;border-bottom:1px solid #ccd4d9}}.note{{padding:16px;background:#f2f6f8}}</style>
    <h1>AeroPKmech · Engineering note</h1><p>Spur gear pair · revision {design.revision} · report {artifact_store.REPORT_VERSION} · {design.updated_at}</p>
    <h2>Requirements</h2><pre>{html.escape(design.requirements.model_dump_json(indent=2))}</pre><h2>Versioned parameter quantities</h2><pre>{html.escape(json.dumps({key: value.model_dump(mode="json") for key, value in design.parameter_quantities.items()}, indent=2))}</pre><h2>Derived results</h2><table>{rows}</table>
    <h2>Verification</h2><ul>{verification}</ul><p>{html.escape(derived['geometry_note'])}</p>
    <div class="note">Educational model only. No safety, fatigue, thermal, materials, standards, manufacturing or real-world suitability claim is made.</div><h2>Assumptions</h2><ul>{assumptions}</ul>"""
    try:
        path, metadata = artifact_store.publish(document.encode("utf-8"), ARTIFACTS, design, "report", "html", artifact_store.REPORT_VERSION)
    except Exception as exc:
        raise ArtifactExecutionError(f"HTML report generation failed: {exc}") from exc
    return FileResponse(path, media_type="text/html", headers=artifact_headers(metadata, design.revision))


@app.get("/api/v1/report.pdf")
def report_pdf():
    design = store.load()
    if design.family == "electric_vehicle":
        output = BytesIO()
        doc = SimpleDocTemplate(output,pagesize=letter,title=f"EV packaging note revision {design.revision}",author="AeroPKmech Studio")
        styles=getSampleStyleSheet()
        p=design.requirements
        doc.build([Paragraph("Concept EV packaging note",styles["Title"]),Paragraph(f"Revision {design.revision} · all dimensions mm · conceptual CAD envelopes only",styles["Normal"]),Spacer(1,12),Paragraph("Specified requirements",styles["Heading2"]),Paragraph(html.escape(p.model_dump_json(indent=2)),styles["Code"]),Paragraph("Versioned parameter quantities",styles["Heading2"]),Paragraph(html.escape(json.dumps({key:value.model_dump(mode="json") for key,value in design.parameter_quantities.items()},indent=2)),styles["Code"]),Spacer(1,12),Paragraph("Limits",styles["Heading2"]),Paragraph("The range value is a target, not a calculation. No mass, structural, crash, thermal, regulatory, safety, or manufacturing verification is provided.",styles["BodyText"]),Paragraph("Assumptions",styles["Heading2"]),*[Paragraph(html.escape(item),styles["BodyText"]) for item in design.assumptions]])
        path,metadata=artifact_store.publish(output.getvalue(),ARTIFACTS,design,"report","pdf",VEHICLE_GENERATOR_VERSION)
        return FileResponse(path,media_type="application/pdf",filename=path.name,headers=artifact_headers(metadata,design.revision))
    derived = derive(design)
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=letter, title=f"AeroPKmech revision {design.revision}", author="AeroPKmech Studio")
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"AeroPKmech - Engineering note ({artifact_store.REPORT_VERSION})", styles["Title"]),
        Paragraph(f"Spur gear pair - revision {design.revision} - {design.updated_at}", styles["Normal"]),
        Spacer(1, 14),
        Paragraph("Requirements", styles["Heading2"]),
        Paragraph(" · ".join(f"{k}: {v}" for k, v in design.requirements.model_dump().items()), styles["BodyText"]),
        Spacer(1, 10),
        Paragraph("Versioned parameter quantities", styles["Heading2"]),
        Paragraph(html.escape(json.dumps({key: value.model_dump(mode="json") for key, value in design.parameter_quantities.items()}, indent=2)), styles["Code"]),
        Paragraph("Calculated results", styles["Heading2"]),
        Table([["Result", "Value"]] + [[key.replace("_", " "), f"{value:.3f}"] for key, value in derived.items() if isinstance(value, (int, float))], colWidths=[300, 150]),
        Spacer(1, 12),
        Paragraph("Verification status", styles["Heading2"]),
        *[
            Paragraph(
                f"{key}: {item.state.value} - {html.escape(item.summary)}"
                + ("<br/>Evidence: " + "; ".join(html.escape(evidence) for evidence in item.evidence) if item.evidence else ""),
                styles["BodyText"],
            )
            for key, item in summarize(design).items()
        ],
        Spacer(1, 8),
        Paragraph(derived["geometry_note"], styles["BodyText"]),
        Spacer(1, 12),
        Paragraph("Assumptions", styles["Heading2"]),
        *[Paragraph(f"- {html.escape(item)}", styles["BodyText"]) for item in design.assumptions],
        Spacer(1, 12),
        Paragraph("Educational model only. No safety, fatigue, thermal, material, standards, manufacturing, or real-world suitability claim is made.", styles["BodyText"]),
    ]
    table = next(item for item in story if isinstance(item, Table))
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9f0f3")), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b7c3cb")), ("PADDING", (0, 0), (-1, -1), 7)]))
    try:
        doc.build(story)
        path, metadata = artifact_store.publish(output.getvalue(), ARTIFACTS, design, "report", "pdf", artifact_store.REPORT_VERSION)
    except Exception as exc:
        raise ArtifactExecutionError(f"PDF report generation failed: {exc}") from exc
    return FileResponse(path, media_type="application/pdf", filename=path.name, headers=artifact_headers(metadata, design.revision))


def artifact_headers(metadata: dict, revision: int, stale: bool = False) -> dict[str, str]:
    return {
        "X-Design-Revision": str(revision),
        "X-Artifact-ID": metadata["artifact_id"],
        "X-Artifact-Kind": metadata["kind"],
        "X-Generator-Version": metadata["generator_version"],
        "X-Artifact-SHA256": metadata["sha256"],
        "X-Artifact-Stale": str(stale).lower(),
    }


@app.get("/api/v1/artifacts")
def get_artifacts():
    design = store.load()
    try:
        return {"current_revision": design.revision, "artifacts": artifact_store.list_artifacts(ARTIFACTS, design)}
    except RuntimeError as exc:
        return JSONResponse(status_code=503, content={"detail": str(exc), "verification": {"state": VerificationState.EXECUTION_ERROR.value}})


@app.get("/api/v1/artifacts/{filename}")
def download_artifact(filename: str):
    if Path(filename).name != filename:
        raise HTTPException(status_code=404, detail="Artifact not found.")
    design = store.load()
    try:
        metadata = next((item for item in artifact_store.list_artifacts(ARTIFACTS, design) if item["filename"] == filename), None)
    except RuntimeError as exc:
        return JSONResponse(status_code=503, content={"detail": str(exc), "verification": {"state": VerificationState.EXECUTION_ERROR.value}})
    if metadata is None:
        raise HTTPException(status_code=404, detail="Artifact not found in the artifact index.")
    path = ARTIFACTS / filename
    if not path.is_file():
        raise HTTPException(status_code=410, detail="The indexed artifact file is no longer available.")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != metadata["sha256"]:
        return JSONResponse(status_code=409, content={"detail": "Artifact bytes do not match their recorded checksum.", "verification": {"state": VerificationState.FAILED.value}})
    media_type = {".stl": "model/stl", ".step": "model/step", ".html": "text/html", ".pdf": "application/pdf", ".json":"application/json"}.get(path.suffix, "application/octet-stream")
    headers = artifact_headers(metadata, metadata["revision"], stale=metadata["stale"])
    return FileResponse(path, media_type=media_type, filename=path.name, headers=headers)


@app.get("/{path:path}")
def static(path: str):
    target = (PUBLIC / (path or "index.html")).resolve()
    if not target.is_relative_to(PUBLIC.resolve()):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    media = {".css": "text/css", ".js": "text/javascript", ".html": "text/html"}.get(target.suffix, "application/octet-stream")
    return FileResponse(target, media_type=media)
