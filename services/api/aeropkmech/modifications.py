"""Component-level interactive modification, change-impact preview, and assembly regeneration."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import artifacts as artifact_store
from .domain import Component, Design, Requirements
from .engineering import derive, lewis_bending_stress, lewis_form_factor

GEAR_COMPONENT_PARAMETER_MAP = {
    "pinion": {
        "teeth": ("pinion_teeth", "count", 8, 80, 1),
        "module_mm": ("module_mm", "mm", 0.5, 6.0, 0.1),
        "face_width_mm": ("face_width_mm", "mm", 2.0, 60.0, 1.0),
        "pressure_angle_deg": ("pressure_angle_deg", "deg", 14.0, 30.0, 0.5),
        "bore_diameter_mm": ("bore_diameter_mm", "mm", 3.0, 50.0, 0.5),
        "hub_diameter_mm": ("hub_diameter_mm", "mm", 4.0, 60.0, 0.5),
        "hub_length_mm": ("hub_length_mm", "mm", 2.0, 60.0, 0.5),
        "keyway_width_mm": ("keyway_width_mm", "mm", 1.0, 20.0, 0.5),
        "keyway_depth_mm": ("keyway_depth_mm", "mm", 0.5, 10.0, 0.5),
    },
    "gear": {
        "teeth": ("gear_teeth", "count", 8, 120, 1),
        "module_mm": ("module_mm", "mm", 0.5, 6.0, 0.1),
        "face_width_mm": ("face_width_mm", "mm", 2.0, 60.0, 1.0),
        "pressure_angle_deg": ("pressure_angle_deg", "deg", 14.0, 30.0, 0.5),
        "bore_diameter_mm": ("bore_diameter_mm", "mm", 3.0, 50.0, 0.5),
        "hub_diameter_mm": ("hub_diameter_mm", "mm", 4.0, 60.0, 0.5),
        "hub_length_mm": ("hub_length_mm", "mm", 2.0, 60.0, 0.5),
        "keyway_width_mm": ("keyway_width_mm", "mm", 1.0, 20.0, 0.5),
        "keyway_depth_mm": ("keyway_depth_mm", "mm", 0.5, 10.0, 0.5),
    },
}


class ComponentEditPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component_id: str = Field(min_length=1, max_length=100)
    expected_revision: int = Field(ge=1)
    parameters: dict[str, float] = Field(min_length=1)


class ComponentEditApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component_id: str = Field(min_length=1, max_length=100)
    expected_revision: int = Field(ge=1)
    parameters: dict[str, float] = Field(min_length=1)


def preview_component_edit(
    current: Design,
    component_id: str,
    parameters: dict[str, float],
    artifacts_dir: Path,
) -> dict[str, Any]:
    """Calculate downstream change-impact preview without mutating the canonical project."""
    if current.family != "spur_gear_pair":
        raise ValueError(f"Component parameter editing is not supported for family {current.family}.")

    if component_id not in GEAR_COMPONENT_PARAMETER_MAP:
        raise ValueError(
            f"Unknown component '{component_id}'. Supported components: {list(GEAR_COMPONENT_PARAMETER_MAP.keys())}"
        )

    allowed_params = GEAR_COMPONENT_PARAMETER_MAP[component_id]
    unknown_keys = set(parameters) - set(allowed_params)
    if unknown_keys:
        raise ValueError(
            f"Unsupported parameter(s) for component '{component_id}': {', '.join(sorted(unknown_keys))}. "
            f"Supported parameters: {', '.join(sorted(allowed_params.keys()))}"
        )

    # Validate numeric bounds
    validation_errors: list[str] = []
    canonical_edits: dict[str, float] = {}
    parameter_changes: list[dict[str, Any]] = []

    p_comp, g_comp = current.components
    current_values_by_component = {
        "pinion": {
            "teeth": p_comp.teeth,
            "module_mm": current.requirements.module_mm,
            "face_width_mm": current.requirements.face_width_mm,
            "pressure_angle_deg": current.requirements.pressure_angle_deg,
            "bore_diameter_mm": current.requirements.bore_diameter_mm,
            "hub_diameter_mm": current.requirements.hub_diameter_mm,
            "hub_length_mm": current.requirements.hub_length_mm,
            "keyway_width_mm": current.requirements.keyway_width_mm,
            "keyway_depth_mm": current.requirements.keyway_depth_mm,
        },
        "gear": {
            "teeth": g_comp.teeth,
            "module_mm": current.requirements.module_mm,
            "face_width_mm": current.requirements.face_width_mm,
            "pressure_angle_deg": current.requirements.pressure_angle_deg,
            "bore_diameter_mm": current.requirements.bore_diameter_mm,
            "hub_diameter_mm": current.requirements.hub_diameter_mm,
            "hub_length_mm": current.requirements.hub_length_mm,
            "keyway_width_mm": current.requirements.keyway_width_mm,
            "keyway_depth_mm": current.requirements.keyway_depth_mm,
        },
    }

    for param_name, proposed_val in parameters.items():
        canonical_name, unit, min_val, max_val, step = allowed_params[param_name]
        if not math.isfinite(proposed_val):
            validation_errors.append(f"{param_name}: value must be a finite number.")
            continue
        if proposed_val < min_val or proposed_val > max_val:
            validation_errors.append(
                f"{param_name}: proposed value {proposed_val} is outside allowed range [{min_val}, {max_val}] {unit}."
            )
            continue
        if unit == "count" and not float(proposed_val).is_integer():
            validation_errors.append(f"{param_name}: tooth count must be an integer.")
            continue

        current_val = current_values_by_component[component_id].get(param_name)
        canonical_edits[canonical_name] = int(proposed_val) if unit == "count" else proposed_val
        parameter_changes.append({
            "component_id": component_id,
            "parameter": param_name,
            "canonical_field": canonical_name,
            "current_value": current_val,
            "proposed_value": proposed_val,
            "unit": unit,
            "changed": current_val != proposed_val,
        })

    if validation_errors:
        return {
            "valid": False,
            "lifecycle_state": "INVALID",
            "component_id": component_id,
            "current_revision": current.revision,
            "target_revision": current.revision + 1,
            "errors": validation_errors,
            "parameter_changes": parameter_changes,
            "dependent_changes": [],
            "affected_components": [],
            "stale_artifacts": [],
            "design_mutated": False,
        }

    # Build candidate in-memory to evaluate cross-field constraints and derived values
    candidate = current.model_copy(deep=True)
    if "pinion_teeth" in canonical_edits:
        candidate.components[0].teeth = int(canonical_edits["pinion_teeth"])
    if "gear_teeth" in canonical_edits:
        candidate.components[1].teeth = int(canonical_edits["gear_teeth"])
    for key, val in canonical_edits.items():
        if key not in {"pinion_teeth", "gear_teeth"}:
            setattr(candidate.requirements, key, val)
    candidate.requirements.gear_ratio = candidate.components[1].teeth / candidate.components[0].teeth

    # Test candidate validation
    try:
        candidate.parameter_quantities = {}
        candidate.parameter_records = {}
        candidate = Design.model_validate(candidate.model_dump(mode="json"))
    except (ValueError, ValidationError) as exc:
        return {
            "valid": False,
            "lifecycle_state": "INVALID",
            "component_id": component_id,
            "current_revision": current.revision,
            "target_revision": current.revision + 1,
            "errors": [str(exc)],
            "parameter_changes": parameter_changes,
            "dependent_changes": [],
            "affected_components": [],
            "stale_artifacts": [],
            "design_mutated": False,
        }

    # Compute downstream dependent quantity changes
    current_derived = derive(current)
    candidate_derived = derive(candidate)

    dependent_fields = [
        ("gear_ratio", "Transmission ratio", "", "{:.2f}"),
        ("center_distance_mm", "Center distance", "mm", "{:.2f}"),
        ("output_speed_rpm", "Ideal output speed", "rpm", "{:.0f}"),
        ("ideal_output_torque_Nm", "Ideal output torque", "N·m", "{:.1f}"),
        ("tangential_load_N", "Tangential load F_t", "N", "{:.1f}"),
        ("pinion_bending_stress_MPa", "Pinion Lewis bending stress", "MPa", "{:.1f}"),
        ("gear_bending_stress_MPa", "Gear Lewis bending stress", "MPa", "{:.1f}"),
    ]

    dependent_changes: list[dict[str, Any]] = []
    for field_name, label, unit, fmt in dependent_fields:
        old_val = current_derived.get(field_name)
        new_val = candidate_derived.get(field_name)
        if old_val is not None and new_val is not None:
            delta = new_val - old_val
            if abs(delta) > 1e-6:
                dependent_changes.append({
                    "parameter": field_name,
                    "label": label,
                    "current_value": old_val,
                    "proposed_value": new_val,
                    "unit": unit,
                    "delta": delta,
                    "formatted_current": fmt.format(old_val),
                    "formatted_proposed": fmt.format(new_val),
                })

    # Component-specific pitch/tip/root/base diameter changes
    comp_labels = {"pinion": "Pinion", "gear": "Driven gear"}
    for cid in ("pinion", "gear"):
        c_old = next((c for c in current_derived.get("components", []) if c.get("id") == cid), {})
        c_new = next((c for c in candidate_derived.get("components", []) if c.get("id") == cid), {})
        for prop, prop_label in [
            ("pitch_diameter_mm", f"{comp_labels[cid]} pitch diameter d_p"),
            ("outer_diameter_mm", f"{comp_labels[cid]} tip diameter d_a"),
            ("root_diameter_mm", f"{comp_labels[cid]} root diameter d_f"),
            ("base_diameter_mm", f"{comp_labels[cid]} base diameter d_b"),
        ]:
            v_old = c_old.get(prop)
            v_new = c_new.get(prop)
            if v_old is not None and v_new is not None and abs(v_new - v_old) > 1e-6:
                dependent_changes.append({
                    "parameter": f"{cid}.{prop}",
                    "label": prop_label,
                    "current_value": v_old,
                    "proposed_value": v_new,
                    "unit": "mm",
                    "delta": v_new - v_old,
                    "formatted_current": f"{v_old:.2f}",
                    "formatted_proposed": f"{v_new:.2f}",
                })

    # Affected components
    affected_components: set[str] = {component_id}
    # If module, face width, or pressure angle changes, both gears change
    if any(k in canonical_edits for k in ("module_mm", "face_width_mm", "pressure_angle_deg")):
        affected_components = {"pinion", "gear"}
    # If teeth of either gear changes, center distance changes so driven gear placement changes
    if any(k in canonical_edits for k in ("pinion_teeth", "gear_teeth")):
        affected_components = {"pinion", "gear"}

    # List stale artifacts
    try:
        current_artifacts = artifact_store.list_artifacts(artifacts_dir, current)
        stale_artifacts = [
            f"{item['kind']} (R{item['revision']})"
            for item in current_artifacts
            if item.get("available")
        ]
    except Exception:
        stale_artifacts = ["gear-reference-drawing", "assembly-step", "assembly-stl", "engineering-report", "gear-bom"]

    # Meshing check limitation note
    meshing_note = (
        f"Nominal center distance shifts from {current_derived['center_distance_mm']:.2f} mm "
        f"to {candidate_derived['center_distance_mm']:.2f} mm. "
        "Generated CAD assembly will update child origins and phase angle. "
        "Geometric engagement is maintained at nominal pitch line; contact kinematics and tooth interference remain unobservable."
    )

    return {
        "valid": True,
        "lifecycle_state": "VALIDATED",
        "component_id": component_id,
        "current_revision": current.revision,
        "target_revision": current.revision + 1,
        "errors": [],
        "parameter_changes": parameter_changes,
        "dependent_changes": dependent_changes,
        "affected_components": sorted(affected_components),
        "stale_artifacts": stale_artifacts,
        "meshing_note": meshing_note,
        "verification_summary": {
            "tooth_strength": "UNKNOWN (Lewis bending stress calculated; material allowables required for verification)",
            "center_distance": f"Center distance: {candidate_derived['center_distance_mm']:.2f} mm (observed origin offset)",
            "ratio": f"Gear ratio: {candidate_derived['gear_ratio']:.3f}",
        },
        "design_mutated": False,
    }


def gear_bom(design: Design) -> dict[str, Any]:
    """Generate structured Bill of Materials for spur gear pair."""
    derived = derive(design)
    req = design.requirements
    p, g = design.components
    p_derived = next((c for c in derived.get("components", []) if c.get("id") == "pinion"), {})
    g_derived = next((c for c in derived.get("components", []) if c.get("id") == "gear"), {})

    components = [
        {
            "item": 1,
            "id": "pinion",
            "name": p.name,
            "role": "Driver / Input gear",
            "quantity": 1,
            "teeth": p.teeth,
            "module_mm": req.module_mm,
            "face_width_mm": req.face_width_mm,
            "pressure_angle_deg": req.pressure_angle_deg,
            "pitch_diameter_mm": p_derived.get("pitch_diameter_mm", req.module_mm * p.teeth),
            "outer_diameter_mm": p_derived.get("outer_diameter_mm", req.module_mm * (p.teeth + 2)),
            "root_diameter_mm": p_derived.get("root_diameter_mm", req.module_mm * (p.teeth - 2.5)),
            "base_diameter_mm": p_derived.get("base_diameter_mm", req.module_mm * p.teeth * math.cos(math.radians(req.pressure_angle_deg))),
            "bore_diameter_mm": derived.get("bore_diameter_mm"),
            "hub_diameter_mm": getattr(req, "hub_diameter_mm", None),
            "hub_length_mm": getattr(req, "hub_length_mm", None),
            "keyway_width_mm": getattr(req, "keyway_width_mm", None),
            "keyway_depth_mm": getattr(req, "keyway_depth_mm", None),
            "lewis_form_factor": p_derived.get("lewis_form_factor"),
            "lewis_bending_stress_MPa": p_derived.get("bending_stress_MPa"),
            "material": "Unspecified (user material specification required)",
        },
        {
            "item": 2,
            "id": "gear",
            "name": g.name,
            "role": "Driven / Output gear",
            "quantity": 1,
            "teeth": g.teeth,
            "module_mm": req.module_mm,
            "face_width_mm": req.face_width_mm,
            "pressure_angle_deg": req.pressure_angle_deg,
            "pitch_diameter_mm": g_derived.get("pitch_diameter_mm", req.module_mm * g.teeth),
            "outer_diameter_mm": g_derived.get("outer_diameter_mm", req.module_mm * (g.teeth + 2)),
            "root_diameter_mm": g_derived.get("root_diameter_mm", req.module_mm * (g.teeth - 2.5)),
            "base_diameter_mm": g_derived.get("base_diameter_mm", req.module_mm * g.teeth * math.cos(math.radians(req.pressure_angle_deg))),
            "bore_diameter_mm": derived.get("bore_diameter_mm"),
            "hub_diameter_mm": getattr(req, "hub_diameter_mm", None),
            "hub_length_mm": getattr(req, "hub_length_mm", None),
            "keyway_width_mm": getattr(req, "keyway_width_mm", None),
            "keyway_depth_mm": getattr(req, "keyway_depth_mm", None),
            "lewis_form_factor": g_derived.get("lewis_form_factor"),
            "lewis_bending_stress_MPa": g_derived.get("bending_stress_MPa"),
            "material": "Unspecified (user material specification required)",
        },
    ]

    return {
        "bom_version": "gear-bom-0.1",
        "project_id": design.id,
        "family": design.family,
        "revision": design.revision,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "assembly": {
            "center_distance_mm": derived.get("center_distance_mm"),
            "gear_ratio": derived.get("gear_ratio"),
            "input_torque_Nm": req.input_torque_Nm,
            "input_speed_rpm": req.input_speed_rpm,
            "output_speed_rpm": derived.get("output_speed_rpm"),
            "ideal_output_torque_Nm": derived.get("ideal_output_torque_Nm"),
            "tangential_load_N": derived.get("tangential_load_N"),
        },
        "components": components,
        "notes": [
            "Bill of Materials reflects canonical design state for the specified revision.",
            "Material specifications, allowable stresses, and safety factors must be supplied by the user.",
            "Bending stresses are calculated using Lewis formula (single-tooth tip load, Kv=1).",
            "This document is an engineering reference BOM, not a manufacturing purchase order.",
        ],
    }
