from __future__ import annotations

import os
import html
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from io import BytesIO

from . import cad, store
from . import artifacts as artifact_store
from .domain import Design, EditRequest, InterpretRequest
from .engineering import calculation_details, derive, validate
from .families import (
    IMPLEMENTED_FAMILIES,
    PLANNED_FAMILY_AREAS,
    FamilyInitializationRequest,
    GearExperimentRequest,
    UnsupportedDesignFamily,
    get_family,
    list_families,
)
from .intelligence import extract
from .verification import VerificationState, summarize

app = FastAPI(title="AeroPKmech API", version="0.2.0", description="Versioned educational spur gear design workflow")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"], allow_methods=["GET", "POST", "PATCH"], allow_headers=["*"])
ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = Path(os.environ.get("AEROPKMECH_ARTIFACTS_DIR", ROOT / "artifacts"))
PUBLIC = ROOT / "public"
THREE_VENDOR = ROOT / "node_modules" / "three"
if THREE_VENDOR.is_dir():
    app.mount("/vendor", StaticFiles(directory=THREE_VENDOR), name="three-vendor")


class ArtifactExecutionError(RuntimeError):
    pass


def response(design: Design) -> dict:
    family = get_family(design.family, design.schema_version)
    family.validate_state(design)
    verification = {key: item.model_dump(mode="json") for key, item in family.verify(design).items()}
    return {**design.model_dump(mode="json"), "derived": family.calculate(design), "calculations": calculation_details(design), "validation": validate(design), "verification": verification}


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
    candidate.revision = current.revision + 1
    candidate.history = [*current.history, {"revision": current.revision, "changed_at": current.updated_at, "design": current.model_dump(mode="json")}]
    candidate.updated_at = datetime.now(timezone.utc).isoformat()
    family.validate_state(candidate)
    store.save(candidate)
    return response(candidate)


@app.post("/api/v1/project/demo")
def restore_demo_project():
    current = store.load()
    candidate = store.default_design()
    candidate.revision = current.revision + 1
    candidate.history = [*current.history, {"revision": current.revision, "changed_at": current.updated_at, "design": current.model_dump(mode="json")}]
    candidate.updated_at = datetime.now(timezone.utc).isoformat()
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
    for key in ("module_mm", "face_width_mm", "input_torque_Nm", "input_speed_rpm"):
        setattr(design.requirements, key, values[key])
    design.requirements.gear_ratio = values["gear_teeth"] / values["pinion_teeth"]
    design.revision = current.revision
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
    values = edit.model_dump(exclude_none=True)
    candidate = current.model_copy(deep=True)
    candidate.history.append({"revision": current.revision, "changed_at": current.updated_at, "design": current.model_dump(mode="json")})
    if "pinion_teeth" in values:
        candidate.components[0].teeth = values.pop("pinion_teeth")
    if "gear_teeth" in values:
        candidate.components[1].teeth = values.pop("gear_teeth")
    for key, value in values.items():
        setattr(candidate.requirements, key, value)
    candidate.requirements.gear_ratio = candidate.components[1].teeth / candidate.components[0].teeth
    candidate.revision += 1
    candidate.updated_at = datetime.now(timezone.utc).isoformat()
    # Validate the complete candidate (including cross-field invariants) before persistence.
    candidate = Design.model_validate(candidate.model_dump(mode="json"))
    store.save(candidate)
    return response(candidate)


@app.post("/api/v1/project/interpret")
async def interpret(request: InterpretRequest):
    return (await extract(request.text)).model_dump(mode="json")


@app.get("/api/v1/export/stl")
def export_stl():
    design = store.load()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    temporary = ARTIFACTS / f".generating-{uuid.uuid4().hex}.stl"
    try:
        cad.export_stl(design, temporary)
        path, metadata = artifact_store.publish(temporary.read_bytes(), ARTIFACTS, design, "assembly", "stl", cad.GENERATOR_VERSION)
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
        cad.export_step(design, temporary)
        path, metadata = artifact_store.publish(temporary.read_bytes(), ARTIFACTS, design, "assembly", "step", cad.GENERATOR_VERSION)
    except Exception as exc:
        raise ArtifactExecutionError(f"CadQuery STEP export failed: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return FileResponse(path, media_type="model/step", filename=path.name, headers=artifact_headers(metadata, design.revision))


@app.get("/api/v1/geometry/{component_id}.stl")
def component_geometry(component_id: Literal["pinion", "gear"], revision: int | None = Query(default=None, ge=1)):
    design = store.load()
    if revision is not None and revision != design.revision:
        raise HTTPException(
            status_code=409,
            detail=f"Requested geometry revision {revision} is not current; project revision is {design.revision}.",
            headers={"X-Design-Revision": str(design.revision)},
        )
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    temporary = ARTIFACTS / f".generating-{uuid.uuid4().hex}.stl"
    try:
        cad.export_component_stl(design, component_id, temporary)
        latest = store.load()
        if latest.revision != design.revision:
            raise HTTPException(
                status_code=409,
                detail=f"Design changed from revision {design.revision} to {latest.revision} while geometry was generated.",
                headers={"X-Design-Revision": str(latest.revision)},
            )
        path, metadata = artifact_store.publish(temporary.read_bytes(), ARTIFACTS, design, component_id, "stl", cad.GENERATOR_VERSION)
    except HTTPException:
        raise
    except Exception as exc:
        raise ArtifactExecutionError(f"CadQuery component tessellation failed: {exc}") from exc
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


@app.get("/api/v1/report", response_class=HTMLResponse)
def report():
    design = store.load()
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
    <h2>Requirements</h2><pre>{html.escape(design.requirements.model_dump_json(indent=2))}</pre><h2>Derived results</h2><table>{rows}</table>
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
    table = story[7]
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
    media_type = {".stl": "model/stl", ".step": "model/step", ".html": "text/html", ".pdf": "application/pdf"}.get(path.suffix, "application/octet-stream")
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
