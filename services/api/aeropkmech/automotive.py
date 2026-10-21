"""Bounded electric-vehicle concept family: provenance, geometry and drawings.

All solids are conceptual envelopes and interface primitives. The family does
not calculate or imply structural, road-safety, crash, range, or performance
fitness.
"""
from __future__ import annotations

import math
import hashlib
import re
import uuid
from functools import lru_cache
from threading import RLock
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import cadquery as cq
from pydantic import BaseModel, ConfigDict, Field, model_validator

VEHICLE_CAD_LOCK = RLock()
VEHICLE_GENERATOR_VERSION = "cq-ev-envelope-0.2"


class SourcedValue(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    value: float = Field(gt=0)
    unit: str
    source: Literal["USER_PROVIDED", "ASSUMED"]
    evidence: str | None = None


class VehicleParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    overall_length_mm: SourcedValue
    overall_width_mm: SourcedValue
    occupant_capacity: int = Field(ge=1, le=12)
    occupant_source: Literal["USER_PROVIDED", "ASSUMED"] = "USER_PROVIDED"
    occupant_evidence: str | None = None
    target_range_km: SourcedValue
    propulsion_type: Literal["electric"] = "electric"
    propulsion_source: Literal["USER_PROVIDED", "ASSUMED"] = "USER_PROVIDED"
    propulsion_evidence: str | None = None
    body_height_mm: SourcedValue
    wheelbase_mm: SourcedValue
    front_track_mm: SourcedValue
    rear_track_mm: SourcedValue
    tire_outer_diameter_mm: SourcedValue
    tire_width_mm: SourcedValue
    ground_clearance_mm: SourcedValue
    frame_rail_width_mm: SourcedValue
    frame_rail_height_mm: SourcedValue
    body_width_mm: SourcedValue
    body_length_mm: SourcedValue
    propulsion_layout: Literal["rear_motor_rear_drive"] = "rear_motor_rear_drive"

    @model_validator(mode="after")
    def consistent_geometry(self):
        p = self
        if p.wheelbase_mm.value >= p.overall_length_mm.value:
            raise ValueError("wheelbase must be shorter than overall length")
        if p.wheelbase_mm.value + p.tire_outer_diameter_mm.value > p.overall_length_mm.value:
            raise ValueError("wheelbase plus tire diameter must fit within the overall length envelope")
        if p.front_track_mm.value >= p.overall_width_mm.value or p.rear_track_mm.value >= p.overall_width_mm.value:
            raise ValueError("track widths must fit inside overall width")
        if p.tire_outer_diameter_mm.value >= p.body_height_mm.value:
            raise ValueError("tire diameter must be shorter than body height")
        if p.body_width_mm.value > p.overall_width_mm.value or p.body_length_mm.value > p.overall_length_mm.value:
            raise ValueError("body envelope must fit within overall dimensions")
        if p.ground_clearance_mm.value >= p.tire_outer_diameter_mm.value / 2:
            raise ValueError("ground clearance must be below wheel-center height")
        if max(p.front_track_mm.value, p.rear_track_mm.value) + p.tire_width_mm.value > p.overall_width_mm.value:
            raise ValueError("track and tire width exceed overall width")
        if p.body_width_mm.value > min(p.front_track_mm.value, p.rear_track_mm.value) - p.tire_width_mm.value:
            raise ValueError("body envelope width must clear the inner faces of the tire envelopes")
        return self


class VehicleDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = "electric-vehicle-concept"
    family: Literal["electric_vehicle"] = "electric_vehicle"
    schema_version: Literal["1.0"] = "1.0"
    revision: int = Field(ge=1)
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    requirements: VehicleParameters
    assumptions: list[str]
    status: dict[str, str]
    source_prompt: str | None = Field(default=None, max_length=4000)
    history: list[dict] = Field(default_factory=list)


class VehicleGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    expected_revision: int = Field(ge=1)
    overall_length_mm: float = Field(gt=1500, le=12000)
    overall_width_mm: float = Field(gt=800, le=4000)
    occupant_capacity: int = Field(ge=1, le=12)
    target_range_km: float = Field(gt=0, le=3000)
    body_height_mm: float = Field(gt=800, le=3000)
    wheelbase_mm: float = Field(gt=1000, le=8000)
    front_track_mm: float = Field(gt=800, le=3000)
    rear_track_mm: float = Field(gt=800, le=3000)
    tire_outer_diameter_mm: float = Field(gt=300, le=1500)
    tire_width_mm: float = Field(gt=100, le=600)
    ground_clearance_mm: float = Field(gt=50, le=500)
    frame_rail_width_mm: float = Field(gt=20, le=300)
    frame_rail_height_mm: float = Field(gt=20, le=400)
    body_width_mm: float = Field(gt=800, le=4000)
    body_length_mm: float = Field(gt=1000, le=12000)
    propulsion_layout: Literal["rear_motor_rear_drive"] = "rear_motor_rear_drive"
    provenance: dict[str, Literal["USER_PROVIDED", "ASSUMED"]] = Field(default_factory=dict)
    evidence: dict[str, str] = Field(default_factory=dict)
    source_prompt: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def valid_provenance(self):
        allowed = set(VehicleParameters.model_fields)
        if not set(self.provenance) <= allowed or not set(self.evidence) <= allowed:
            raise ValueError("Vehicle provenance contains an unsupported parameter name.")
        for key, evidence in self.evidence.items():
            if not evidence or not self.source_prompt or evidence not in self.source_prompt:
                raise ValueError(f"Evidence for {key} must be an exact span of source_prompt.")
        if any(source == "USER_PROVIDED" for source in self.provenance.values()) and not self.source_prompt:
            raise ValueError("A source_prompt is required for user-provided vehicle provenance.")
        return self


class VehicleParameterEditRequest(BaseModel):
    """Allowlisted geometry parameters for an optimistic EV revision edit."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    expected_revision: int = Field(ge=1)
    overall_length_mm: float | None = Field(default=None, gt=1500, le=12000)
    overall_width_mm: float | None = Field(default=None, gt=800, le=4000)
    body_height_mm: float | None = Field(default=None, gt=800, le=3000)
    wheelbase_mm: float | None = Field(default=None, gt=1000, le=8000)
    front_track_mm: float | None = Field(default=None, gt=800, le=3000)
    rear_track_mm: float | None = Field(default=None, gt=800, le=3000)
    tire_outer_diameter_mm: float | None = Field(default=None, gt=300, le=1500)
    tire_width_mm: float | None = Field(default=None, gt=100, le=600)
    ground_clearance_mm: float | None = Field(default=None, gt=50, le=500)
    frame_rail_width_mm: float | None = Field(default=None, gt=20, le=300)
    frame_rail_height_mm: float | None = Field(default=None, gt=20, le=400)
    body_width_mm: float | None = Field(default=None, gt=800, le=4000)
    body_length_mm: float | None = Field(default=None, gt=1000, le=12000)

    @model_validator(mode="after")
    def at_least_one_geometry_edit(self):
        if not any(getattr(self, name) is not None for name in type(self).model_fields if name != "expected_revision"):
            raise ValueError("Provide at least one supported geometry parameter.")
        return self


VEHICLE_EDITABLE_PARAMETERS = {
    "overall_length_mm": {"label": "Overall length", "unit": "mm", "min_exclusive": 1500, "max": 12000, "step": 10, "dependencies": ["body-envelope", "frame-rail-left", "frame-rail-right", "front-crossmember", "rear-crossmember", "front/rear wheels when assumed wheelbase propagates"]},
    "overall_width_mm": {"label": "Overall width", "unit": "mm", "min_exclusive": 800, "max": 4000, "step": 10, "dependencies": ["front/rear wheels when assumed tracks propagate", "body-envelope when assumed body width propagates"]},
    "body_height_mm": {"label": "Body envelope height", "unit": "mm", "min_exclusive": 800, "max": 3000, "step": 10, "dependencies": ["body-envelope"]},
    "wheelbase_mm": {"label": "Wheelbase", "unit": "mm", "min_exclusive": 1000, "max": 8000, "step": 10, "dependencies": ["front/rear axles", "wheel/rim/hub/link groups", "frame members", "battery/motor/inverter/reduction envelopes"]},
    "front_track_mm": {"label": "Front track", "unit": "mm", "min_exclusive": 800, "max": 3000, "step": 10, "dependencies": ["front axle and wheel/rim/hub/link group"]},
    "rear_track_mm": {"label": "Rear track", "unit": "mm", "min_exclusive": 800, "max": 3000, "step": 10, "dependencies": ["rear axle and wheel/rim/hub/link group", "frame width", "battery envelope"]},
    "tire_outer_diameter_mm": {"label": "Tire outer diameter", "unit": "mm", "min_exclusive": 300, "max": 1500, "step": 5, "dependencies": ["all tire/rim groups", "wheel centers", "motor/reduction placement"]},
    "tire_width_mm": {"label": "Tire width", "unit": "mm", "min_exclusive": 100, "max": 600, "step": 5, "dependencies": ["all tire/rim groups"]},
    "ground_clearance_mm": {"label": "Ground clearance", "unit": "mm", "min_exclusive": 50, "max": 500, "step": 5, "dependencies": ["frame height", "body envelope", "suspension links", "battery/inverter placement"]},
    "frame_rail_width_mm": {"label": "Frame rail width", "unit": "mm", "min_exclusive": 20, "max": 300, "step": 5, "dependencies": ["frame rails and crossmembers"]},
    "frame_rail_height_mm": {"label": "Frame rail height", "unit": "mm", "min_exclusive": 20, "max": 400, "step": 5, "dependencies": ["frame rails", "crossmembers", "suspension and propulsion package placement"]},
    "body_width_mm": {"label": "Body envelope width", "unit": "mm", "min_exclusive": 800, "max": 4000, "step": 10, "dependencies": ["body-envelope"]},
    "body_length_mm": {"label": "Body envelope length", "unit": "mm", "min_exclusive": 1000, "max": 12000, "step": 10, "dependencies": ["body-envelope"]},
}

VEHICLE_COMPONENT_PARAMETER_DEPENDENCIES = {
    "frame-rail-left": ("overall_length_mm","overall_width_mm","wheelbase_mm","rear_track_mm","ground_clearance_mm","frame_rail_width_mm","frame_rail_height_mm"),
    "frame-rail-right": ("overall_length_mm","overall_width_mm","wheelbase_mm","rear_track_mm","ground_clearance_mm","frame_rail_width_mm","frame_rail_height_mm"),
    "front-crossmember": ("overall_length_mm","overall_width_mm","wheelbase_mm","rear_track_mm","ground_clearance_mm","frame_rail_width_mm","frame_rail_height_mm"),
    "rear-crossmember": ("overall_length_mm","overall_width_mm","wheelbase_mm","rear_track_mm","ground_clearance_mm","frame_rail_width_mm","frame_rail_height_mm"),
    "front-axle-reference": ("overall_length_mm","overall_width_mm","wheelbase_mm","front_track_mm","tire_outer_diameter_mm"),
    "rear-axle-reference": ("overall_length_mm","overall_width_mm","wheelbase_mm","rear_track_mm","tire_outer_diameter_mm"),
    "body-envelope": ("overall_length_mm","overall_width_mm","body_height_mm","ground_clearance_mm","body_width_mm","body_length_mm"),
    "battery-pack-envelope": ("wheelbase_mm","rear_track_mm","ground_clearance_mm","frame_rail_height_mm"),
    "traction-motor-envelope": ("wheelbase_mm","tire_outer_diameter_mm"),
    "inverter-envelope": ("wheelbase_mm","ground_clearance_mm","frame_rail_height_mm"),
    "reduction-drive-envelope": ("wheelbase_mm","tire_outer_diameter_mm"),
}
for _axle in ("front","rear"):
    _track=f"{_axle}_track_mm"
    for _side in ("left","right"):
        _wheel=f"{_axle}-{_side}"
        VEHICLE_COMPONENT_PARAMETER_DEPENDENCIES[f"tire-{_wheel}"]=("overall_length_mm","overall_width_mm","wheelbase_mm",_track,"tire_outer_diameter_mm","tire_width_mm")
        VEHICLE_COMPONENT_PARAMETER_DEPENDENCIES[f"rim-{_wheel}"]=("overall_length_mm","overall_width_mm","wheelbase_mm",_track,"tire_outer_diameter_mm","tire_width_mm")
        VEHICLE_COMPONENT_PARAMETER_DEPENDENCIES[f"hub-{_wheel}"]=("wheelbase_mm",_track,"tire_outer_diameter_mm")
        VEHICLE_COMPONENT_PARAMETER_DEPENDENCIES[f"suspension-link-{_wheel}"]=("wheelbase_mm",_track,"tire_outer_diameter_mm","ground_clearance_mm","frame_rail_height_mm")


class VehiclePromptParameter(BaseModel):
    name: str
    meaning: str
    value: float | int | str | None
    unit: str
    source: str
    evidence: str | None
    status: str
    canonical_target: str | None = None
    source_span: dict[str, int | str] | None = None
    constraints: list[str] = Field(default_factory=list)
    affected_components: list[str] = Field(default_factory=list)


class VehiclePromptNode(BaseModel):
    id: str
    name: str
    kind: str
    parent_id: str | None = None
    role: str
    parameter_refs: list[str] = []


class VehiclePromptRelationship(BaseModel):
    id: str
    source_id: str
    target_id: str
    relationship: str
    status: Literal["CONCEPTUAL_ONLY", "NEEDS_INPUT"] = "CONCEPTUAL_ONLY"


class VehicleConcept(BaseModel):
    system_name: str
    parameters: list[VehiclePromptParameter]
    nodes: list[VehiclePromptNode]
    relationships: list[VehiclePromptRelationship]
    unresolved_questions: list[str]
    validation_issues: list[str]
    conflicts: list[str] = Field(default_factory=list)
    unsupported_requests: list[str] = Field(default_factory=list)
    limitations: list[str]
    assumptions: list[str]


def make_vehicle_design(request: VehicleGenerationRequest, revision: int, history: list[dict]) -> VehicleDesign:
    values = request.model_dump(exclude={"expected_revision", "provenance", "evidence", "source_prompt"})
    provenance = request.provenance
    evidence = request.evidence
    units = {
        "overall_length_mm": "mm", "overall_width_mm": "mm", "occupant_capacity": "persons",
        "target_range_km": "km", "body_height_mm": "mm", "wheelbase_mm": "mm",
        "front_track_mm": "mm", "rear_track_mm": "mm", "tire_outer_diameter_mm": "mm",
        "tire_width_mm": "mm", "ground_clearance_mm": "mm", "frame_rail_width_mm": "mm",
        "frame_rail_height_mm": "mm", "body_width_mm": "mm", "body_length_mm": "mm",
        "propulsion_layout": "",
    }
    sourced = {}
    for name, value in values.items():
        if name == "propulsion_layout":
            sourced[name] = value
        elif name == "occupant_capacity":
            sourced[name] = value
        else:
            sourced[name] = SourcedValue(
                value=value, unit=units[name], source=provenance.get(name, "ASSUMED"), evidence=evidence.get(name)
            )
    sourced["occupant_source"] = provenance.get("occupant_capacity", "ASSUMED")
    sourced["occupant_evidence"] = evidence.get("occupant_capacity")
    sourced["propulsion_source"] = provenance.get("propulsion_type", "ASSUMED")
    sourced["propulsion_evidence"] = evidence.get("propulsion_type")
    assumed = [
        f"{name}={value} {units.get(name, '')} is a configurable conceptual-geometry default."
        for name, value in values.items() if name not in {"occupant_capacity", "propulsion_layout"} and provenance.get(name) != "USER_PROVIDED"
    ]
    assumed.extend([
        "Vehicle coordinates use X longitudinal (front +), Y lateral (left +), Z vertical (up +); ground is Z=0.",
        "Frame members use rectangular 60 mm-wide rails and cross-members from the configurable geometry parameters.",
        "Battery, motor, inverter and reduction-drive solids are packaging envelopes only; internal design and ratings are unresolved.",
    ])
    return VehicleDesign(
        id=f"local-{uuid.uuid4().hex[:12]}", revision=revision,
        requirements=VehicleParameters.model_validate(sourced), assumptions=assumed,
        status={"geometry": "CALCULATED", "dimensional_checks": "CALCULATED", "range": "UNRESOLVED", "safety": "UNSUPPORTED"},
        source_prompt=request.source_prompt,
        history=history,
    )


def propose_electric_vehicle(text: str) -> VehicleConcept:
    """Extract prompt values, record assumed envelope inputs, and expose generation scope."""
    specs: list[VehiclePromptParameter] = []
    evidence: dict[str, str] = {}
    numeric: dict[str, float | int] = {}
    conflicts: list[str] = []
    unsupported_requests: list[str] = []
    seat_match = re.search(r"\b(two|three|four|five|six|\d+)\s*[- ]?seater\b", text, re.I)
    seats = {"two":2,"three":3,"four":4,"five":5,"six":6}.get(seat_match.group(1).lower()) if seat_match else None
    if seat_match and seats is None: seats=int(seat_match.group(1))
    seat_matches=list(re.finditer(r"\b(two|three|four|five|six|\d+)\s*[- ]?seater\b",text,re.I))
    parsed_seats=[{"two":2,"three":3,"four":4,"five":5,"six":6}.get(found.group(1).lower(),int(found.group(1)) if found.group(1).isdigit() else None) for found in seat_matches]
    if len(set(parsed_seats))>1: conflicts.append("Conflicting explicit seating capacities: " + "; ".join(found.group(0) for found in seat_matches))
    for name, meaning, patterns, unit, integer in [
        ("occupant_capacity","Seating capacity",[r"\b(two|three|four|five|six|\d+)\s*[- ]?seater\b"],"persons",True),
        ("overall_length_mm","Overall length",[r"\b(\d+(?:\.\d+)?)\s*(mm|cm|m|millimet(?:er|re)s?|centimet(?:er|re)s?|met(?:er|re)s?)\s+long\b",r"\blength\s*(?:of|is|=|:)?\s*(\d+(?:\.\d+)?)\s*(mm|cm|m|millimet(?:er|re)s?|centimet(?:er|re)s?|met(?:er|re)s?)\b"],"mm",False),
        ("overall_width_mm","Overall width",[r"\b(\d+(?:\.\d+)?)\s*(mm|cm|m|millimet(?:er|re)s?|centimet(?:er|re)s?|met(?:er|re)s?)\s+wide\b",r"\bwidth\s*(?:of|is|=|:)?\s*(\d+(?:\.\d+)?)\s*(mm|cm|m|millimet(?:er|re)s?|centimet(?:er|re)s?|met(?:er|re)s?)\b"],"mm",False),
        ("target_range_km","Target driving range",[r"\b(\d+(?:\.\d+)?)\s*(?:km|kilomet(?:er|re)s?)\s+range\b",r"\brange\s*(?:of|is|=|:)?\s*(\d+(?:\.\d+)?)\s*(?:km|kilomet(?:er|re)s?)\b"],"km",False),
    ]:
        if name=="occupant_capacity":
            value=seats; match=seat_match
        else:
            matches=[]
            for pattern in patterns:
                matches.extend(re.finditer(pattern,text,re.I))
            unique_matches=[]
            seen_spans=set()
            for found in matches:
                if (found.start(),found.end()) not in seen_spans:
                    unique_matches.append(found);seen_spans.add((found.start(),found.end()))
            match=unique_matches[0] if unique_matches else None
            value=None
            if unique_matches:
                converted=[]
                for found in unique_matches:
                    groups=found.groups()
                    number=float(groups[0])
                    if name=="overall_length_mm" or name=="overall_width_mm":
                        unit_raw=groups[1].lower(); number*=1 if unit_raw=="mm" or unit_raw.startswith("millimeter") or unit_raw.startswith("millimetre") else 10 if unit_raw=="cm" or unit_raw.startswith("centimeter") or unit_raw.startswith("centimetre") else 1000
                    converted.append(number)
                value=converted[0]
                if any(not math.isclose(number,value,rel_tol=0,abs_tol=1e-6) for number in converted[1:]):
                    conflicts.append(f"Conflicting explicit values for {name}: " + "; ".join(found.group(0) for found in unique_matches))
            if match:
                groups=match.groups()
                number=float(groups[0])
                if name=="overall_length_mm" or name=="overall_width_mm":
                    unit_raw=groups[1].lower(); number*=1 if unit_raw=="mm" or unit_raw.startswith("millimeter") or unit_raw.startswith("millimetre") else 10 if unit_raw=="cm" or unit_raw.startswith("centimeter") or unit_raw.startswith("centimetre") else 1000
                value=number if value is None else value
        source="user-provided" if value is not None else "missing"
        if value is not None:
            numeric[name]=int(value) if integer else float(value)
            evidence[name]=match.group(0)
        specs.append(VehiclePromptParameter(name=name,meaning=meaning,value=value,unit=unit,source=source,evidence=match.group(0) if match else None,status="PROPOSED" if value is not None else "MISSING"))
    propulsion=bool(re.search(r"\b(electric|EV|battery[ -]electric)\b",text,re.I))
    if propulsion and re.search(r"\b(?:gasoline|petrol|diesel|combustion engine|internal combustion|hybrid)\b",text,re.I):
        conflicts.append("Conflicting propulsion request: electric and combustion/hybrid propulsion are both named.")
    specs.append(VehiclePromptParameter(name="propulsion_type",meaning="Propulsion type",value="electric" if propulsion else None,unit="",source="user-provided" if propulsion else "missing",evidence=(re.search(r"\b(electric|EV|battery[ -]electric)\b",text,re.I).group(0) if propulsion else None),status="PROPOSED" if propulsion else "MISSING"))
    defaults={"body_height_mm":1400,"wheelbase_mm":(numeric.get("overall_length_mm",4200)*.60),"front_track_mm":numeric.get("overall_width_mm",1800)*.875,"rear_track_mm":numeric.get("overall_width_mm",1800)*.875,"tire_outer_diameter_mm":650,"tire_width_mm":225,"ground_clearance_mm":150,"frame_rail_width_mm":60,"frame_rail_height_mm":80,"body_width_mm":numeric.get("overall_width_mm",1800)*.70,"body_length_mm":numeric.get("overall_length_mm",4200)}
    names={"body_height_mm":"Body envelope height","wheelbase_mm":"Wheelbase","front_track_mm":"Front track width","rear_track_mm":"Rear track width","tire_outer_diameter_mm":"Tire outer diameter","tire_width_mm":"Tire section width","ground_clearance_mm":"Ground clearance","frame_rail_width_mm":"Chassis rail width","frame_rail_height_mm":"Chassis rail height","body_width_mm":"Body envelope width","body_length_mm":"Body envelope length"}
    aliases={"body_height_mm":r"body height|overall height|vehicle height","wheelbase_mm":r"wheelbase","front_track_mm":r"front track","rear_track_mm":r"rear track","tire_outer_diameter_mm":r"(?:tire|tyre)(?: outer)? diameter","tire_width_mm":r"(?:tire|tyre) width","ground_clearance_mm":r"ground clearance","frame_rail_width_mm":r"frame rail width","frame_rail_height_mm":r"frame rail height","body_width_mm":r"body envelope width","body_length_mm":r"body envelope length"}
    for name,value in defaults.items():
        founds=list(re.finditer(rf"(?:{aliases[name]})\s*(?:of|is|=|:)?\s*(\d+(?:\.\d+)?)\s*(mm|cm|m)\b",text,re.I))
        found=founds[0] if founds else None
        converted=[float(item.group(1))*(1 if item.group(2).lower()=="mm" else 10 if item.group(2).lower()=="cm" else 1000) for item in founds]
        captured=converted[0] if converted else value
        if any(not math.isclose(item,captured,rel_tol=0,abs_tol=1e-6) for item in converted[1:]):
            conflicts.append(f"Conflicting explicit values for {name}: " + "; ".join(item.group(0) for item in founds))
        specs.append(VehiclePromptParameter(name=name,meaning=names[name],value=captured,unit="mm",source="user-provided" if found else "assumed",evidence=found.group(0) if found else None,status="PROPOSED" if found else "ASSUMED"))
        numeric[name]=captured
    specs.append(VehiclePromptParameter(name="propulsion_layout",meaning="Propulsion layout",value="rear_motor_rear_drive",unit="",source="assumed",evidence=None,status="ASSUMED"))
    numeric["propulsion_layout"]="rear_motor_rear_drive"
    issues=[]
    for parameter in specs:
        if parameter.value is None or not isinstance(parameter.value,(float,int)):
            continue
        bounds=VEHICLE_EDITABLE_PARAMETERS.get(parameter.name)
        if bounds:
            invalid=not bounds["min_exclusive"] < parameter.value <= bounds["max"]
        elif parameter.name=="target_range_km":
            invalid=not 0 < parameter.value <= 3000
        elif parameter.name=="occupant_capacity":
            invalid=not isinstance(parameter.value,int) or not 1 <= parameter.value <= 12
        else:
            invalid=False
        if invalid:
            issues.append(f"{parameter.name}={parameter.value} outside its supported range.")
            parameter.status="INVALID"
    required_values=("occupant_capacity","overall_length_mm","overall_width_mm","target_range_km")
    if all(numeric.get(name) is not None for name in required_values) and propulsion:
        candidate_values={}
        for parameter_name in ("overall_length_mm","overall_width_mm",*defaults):
            source="USER_PROVIDED" if any(item.name==parameter_name and item.source=="user-provided" for item in specs) else "ASSUMED"
            candidate_values[parameter_name]=SourcedValue(value=numeric[parameter_name],unit="mm",source=source)
        candidate_values.update({"occupant_capacity":int(numeric["occupant_capacity"]),"target_range_km":SourcedValue(value=numeric["target_range_km"],unit="km",source="USER_PROVIDED"),"propulsion_type":"electric","propulsion_layout":"rear_motor_rear_drive"})
        try:
            VehicleParameters.model_validate(candidate_values)
        except Exception as exc:
            issues.append(f"Cross-field packaging validation failed: {exc}")
    unsupported_units = list(re.finditer(r"\b\d+(?:\.\d+)?\s*(?:ft|feet|foot|in|inch|inches)\b", text, re.I))
    for found in unsupported_units:
        unsupported_requests.append(f"Unsupported dimension unit: {found.group(0)}. Supply this dimension in mm, cm, or m.")
    unsupported_systems = {
        "braking system": r"\bbrak(?:e|ing)\b",
        "steering system": r"\bsteer(?:ing)?\b",
        "charging system": r"\bcharg(?:e|ing)\b",
        "electrical wiring or voltage architecture": r"\b(?:wiring|voltage architecture|high.voltage architecture)\b",
        "motor power or torque sizing": r"\b(?:motor|traction motor)\s+(?:power|rating|torque)\b|\b(?:kW|Nm)\s+(?:motor|traction)\b",
        "battery capacity or range sizing": r"\b(?:battery capacity|kWh|energy consumption|range sizing|range calculation)\b",
        "validated suspension kinematics": r"\b(?:suspension kinematics|suspension geometry|suspension travel)\b",
        "mass or weight estimate": r"\b(?:mass|weight|payload)\b",
    }
    for label, pattern in unsupported_systems.items():
        found=re.search(pattern,text,re.I)
        if found: unsupported_requests.append(f"Requested {label} is not generated or verified by the conceptual packaging envelope family (evidence: {found.group(0)}).")
    if re.search(r"\b(?:necessary|complete|full)\s+(?:mechanical\s+(?:and\s+)?electrical|electrical\s+(?:and\s+)?mechanical)\s+systems\b",text,re.I):
        unsupported_requests.append("The broad request for complete mechanical/electrical systems exceeds the generated packaging envelopes; only named concept envelopes are available.")
    nodes=[VehiclePromptNode(id="vehicle-assembly",name="Concept electric vehicle",kind="assembly",role="Top-level EV package",parameter_refs=list(numeric))]
    groups={"chassis":["frame-rail-left","frame-rail-right","front-crossmember","rear-crossmember","front-axle-reference","rear-axle-reference"],"wheels":[f"{kind}-{axle}-{side}" for axle in ("front","rear") for side in ("left","right") for kind in ("tire","rim","hub","suspension-link")],"body":["body-envelope"],"propulsion":["battery-pack-envelope","traction-motor-envelope","inverter-envelope","reduction-drive-envelope"]}
    for family,ids in groups.items():
        family_refs=sorted({ref for cid in ids for ref in VEHICLE_COMPONENT_PARAMETER_DEPENDENCIES.get(cid,())})
        nodes.append(VehiclePromptNode(id=family,name=family.replace("_"," ").title(),kind="subsystem",parent_id="vehicle-assembly",role=f"Conceptual {family} subsystem",parameter_refs=family_refs))
        for cid in ids:
            refs=list(VEHICLE_COMPONENT_PARAMETER_DEPENDENCIES.get(cid,()))
            nodes.append(VehiclePromptNode(id=cid,name=cid.replace("-"," ").title(),kind="component",parent_id=family,role=COMPONENT_INFO.get(cid,(cid,family,cid))[2],parameter_refs=refs))
    relationships=[VehiclePromptRelationship(id="rear-motor-to-drive",source_id="traction-motor-envelope",target_id="reduction-drive-envelope",relationship="intended drivetrain packaging association",status="CONCEPTUAL_ONLY"),VehiclePromptRelationship(id="battery-to-inverter",source_id="battery-pack-envelope",target_id="inverter-envelope",relationship="intended electrical packaging association",status="CONCEPTUAL_ONLY")]
    component_refs = {key:list(value) for key,value in VEHICLE_COMPONENT_PARAMETER_DEPENDENCIES.items()}
    for item in specs:
        item.canonical_target=f"requirements.{item.name}"
        item.constraints=[f"{VEHICLE_EDITABLE_PARAMETERS[item.name]['min_exclusive']} < {item.name} <= {VEHICLE_EDITABLE_PARAMETERS[item.name]['max']} {item.unit}"] if item.name in VEHICLE_EDITABLE_PARAMETERS else (["integer 1..12 persons"] if item.name=="occupant_capacity" else (["target only; 0 < value <= 3000 km; range is not calculated"] if item.name=="target_range_km" else ["must be electric"] if item.name=="propulsion_type" else []))
        item.affected_components=[cid for cid,refs in component_refs.items() if item.name in refs]
        if item.evidence:
            start=text.find(item.evidence)
            if start>=0: item.source_span={"start":start,"end":start+len(item.evidence),"text":item.evidence}
    unresolved=[f"Provide {item.meaning.lower()}" for item in specs if item.status=="MISSING"]+["Review assumed wheelbase, tracks, tires, ground clearance, body height, and envelope placements.","Range, mass, performance, strength, crash, thermal, and safety calculations are unsupported."]
    return VehicleConcept(system_name=f"{seats}-seat electric sports car" if seats else "Electric vehicle concept",parameters=specs,nodes=nodes,relationships=relationships,unresolved_questions=unresolved,validation_issues=issues,conflicts=conflicts,unsupported_requests=unsupported_requests,limitations=["Conceptual CAD envelopes only; no strength, crashworthiness, range sizing, dynamics, thermal, safety, or manufacturing validation.","300 km remains a user target, not a calculated range."],assumptions=["Only prompt-stated values are labeled user-provided; missing packaging values are explicit configurable assumptions.","Vehicle coordinates: X forward, Y left, Z up; units mm."])


def _box_center(length: float, width: float, height: float, center: tuple[float, float, float]) -> cq.Workplane:
    return cq.Workplane("XY").box(length, width, height).translate(center)


def _wheel_ring(outer_d: float, width: float, inner_d: float) -> cq.Workplane:
    # Ring axis starts on local Z then rotates to the vehicle's lateral Y axis.
    ring = cq.Workplane("XY").circle(outer_d / 2).circle(inner_d / 2).extrude(width / 2, both=True)
    return ring.rotate((0, 0, 0), (1, 0, 0), 90)


@lru_cache(maxsize=3)
def _vehicle_component_solids_cached(design_json: str) -> dict[str, cq.Workplane]:
    design = VehicleDesign.model_validate_json(design_json)
    p = design.requirements
    length, width = p.overall_length_mm.value, p.overall_width_mm.value
    wheelbase, tire_d, tire_w = p.wheelbase_mm.value, p.tire_outer_diameter_mm.value, p.tire_width_mm.value
    front_x, rear_x = wheelbase / 2, -wheelbase / 2
    front_z = rear_z = tire_d / 2
    front_y, rear_y = p.front_track_mm.value / 2, p.rear_track_mm.value / 2
    clearance = p.ground_clearance_mm.value
    rail_z = clearance + p.frame_rail_height_mm.value / 2
    # Frame is multiple real members, not a vehicle-sized placeholder box.
    frame_length = wheelbase * 0.92
    frame_width = p.rear_track_mm.value * 0.78
    rail_w, rail_h = p.frame_rail_width_mm.value, p.frame_rail_height_mm.value
    solids: dict[str, cq.Workplane] = {
        "frame-rail-left": _box_center(frame_length, rail_w, rail_h, (0, frame_width / 2, rail_z)),
        "frame-rail-right": _box_center(frame_length, rail_w, rail_h, (0, -frame_width / 2, rail_z)),
        "front-crossmember": _box_center(rail_h, frame_width + rail_w, rail_w, (front_x * 0.77, 0, rail_z)),
        "rear-crossmember": _box_center(rail_h, frame_width + rail_w, rail_w, (rear_x * 0.77, 0, rail_z)),
    }
    # Explicit wheel/axle mounting reference geometry and four distinct tires/rims.
    for axle, x, track, z in (("front", front_x, p.front_track_mm.value, front_z), ("rear", rear_x, p.rear_track_mm.value, rear_z)):
        axle_length = track + 100
        solids[f"{axle}-axle-reference"] = _wheel_ring(70, axle_length, 30).translate((x, 0, z))
        for side, sign in (("left", 1), ("right", -1)):
            y = sign * track / 2
            wheel_id = f"{axle}-{side}"
            solids[f"tire-{wheel_id}"] = _wheel_ring(tire_d, tire_w, tire_d * 0.72).translate((x, y, z))
            solids[f"rim-{wheel_id}"] = _wheel_ring(tire_d * 0.70, tire_w * 0.72, 70).translate((x, y, z))
            hub = cq.Workplane("XY").circle(45).extrude(tire_w * 0.4, both=True).rotate((0,0,0),(1,0,0),90).translate((x,y,z))
            solids[f"hub-{wheel_id}"] = hub
            arm_end = (x * 0.86, y * 0.48, clearance + rail_h)
            arm_start = (x, y * 0.78, z)
            dx, dy, dz = (arm_end[i] - arm_start[i] for i in range(3))
            arm_length = math.sqrt(dx*dx + dy*dy + dz*dz)
            arm = cq.Workplane("XY").box(arm_length, 36, 28).translate((arm_length/2,0,0))
            axis = cq.Vector(0,-dz,dy)
            angle = math.degrees(math.acos(max(-1,min(1,dx/arm_length))))
            if axis.Length > 1e-9:
                arm = arm.rotate((0,0,0), axis.toTuple(), angle)
            arm = arm.translate(arm_start)
            solids[f"suspension-link-{wheel_id}"] = arm
    body_h = p.body_height_mm.value
    body_len, body_width = p.body_length_mm.value, p.body_width_mm.value
    # Side silhouette, extruded to an explicit body-envelope width.
    profile = [(-body_len/2, clearance+180), (-body_len/2+250, clearance+650),
               (-body_len*0.20, body_h*0.77), (body_len*0.08, body_h),
               (body_len*0.30, body_h*0.91), (body_len/2, clearance+650),
               (body_len/2, clearance+180)]
    body = cq.Workplane("XZ").polyline(profile).close().extrude(body_width/2, both=True)
    solids["body-envelope"] = body
    # Distinct packaging envelopes, deliberately not inferred ratings.
    solids["battery-pack-envelope"] = _box_center(wheelbase*0.48, p.rear_track_mm.value*0.72, 150, (-50, 0, clearance + rail_h + 90))
    solids["traction-motor-envelope"] = cq.Workplane("XY").circle(130).extrude(260, both=True).rotate((0,0,0),(0,1,0),90).translate((rear_x*0.72,0,tire_d*0.54))
    solids["inverter-envelope"] = _box_center(320, 260, 120, (rear_x*0.37, 0, clearance + rail_h + 240))
    solids["reduction-drive-envelope"] = _box_center(300, 280, 220, (rear_x*0.88, 0, tire_d*0.53))
    return solids


def vehicle_component_solids(design: VehicleDesign) -> dict[str, cq.Workplane]:
    with VEHICLE_CAD_LOCK:
        return _vehicle_component_solids_cached(design.model_dump_json())


COMPONENT_INFO = {
    "frame-rail-left": ("Left longitudinal chassis rail", "chassis", "Frame member"),
    "frame-rail-right": ("Right longitudinal chassis rail", "chassis", "Frame member"),
    "front-crossmember": ("Front chassis crossmember", "chassis", "Frame member"),
    "rear-crossmember": ("Rear chassis crossmember", "chassis", "Frame member"),
    "front-axle-reference": ("Front axle mounting reference", "running_gear", "Mounting reference"),
    "rear-axle-reference": ("Rear axle mounting reference", "running_gear", "Mounting reference"),
    "body-envelope": ("Body envelope", "body", "Exterior packaging envelope"),
    "battery-pack-envelope": ("Battery pack envelope", "electric_propulsion", "HV energy storage packaging"),
    "traction-motor-envelope": ("Traction motor envelope", "electric_propulsion", "Rear traction motor packaging"),
    "inverter-envelope": ("Inverter envelope", "electric_propulsion", "Power electronics packaging"),
    "reduction-drive-envelope": ("Reduction drive envelope", "electric_propulsion", "Rear drive packaging"),
}
for axle in ("front", "rear"):
    for side in ("left", "right"):
        _wheel = f"{axle}-{side}"
        COMPONENT_INFO[f"tire-{_wheel}"] = (f"{axle.title()} {side} tire", "wheel_tire", "Road-contact tire envelope")
        COMPONENT_INFO[f"rim-{_wheel}"] = (f"{axle.title()} {side} rim", "wheel_tire", "Wheel rim envelope")
        COMPONENT_INFO[f"hub-{_wheel}"] = (f"{axle.title()} {side} hub", "wheel_tire", "Wheel hub envelope")
        COMPONENT_INFO[f"suspension-link-{_wheel}"] = (f"{axle.title()} {side} suspension link", "suspension", "Illustrative linkage envelope")


def vehicle_manifest(design: VehicleDesign) -> dict:
    solids = vehicle_component_solids(design)
    p = design.requirements
    items = []
    for component_id, solid in solids.items():
        name, family, role = COMPONENT_INFO[component_id]
        bounds = solid.val().BoundingBox()
        dimensions = {"length_mm": round(bounds.xlen, 4), "width_mm": round(bounds.ylen, 4), "height_mm": round(bounds.zlen, 4)}
        center = {"x_mm": round((bounds.xmin + bounds.xmax)/2, 4), "y_mm": round((bounds.ymin + bounds.ymax)/2, 4), "z_mm": round((bounds.zmin + bounds.zmax)/2, 4)}
        subsystem = family
        component_interfaces = []
        if component_id.startswith(("tire-", "rim-", "hub-", "suspension-link-")):
            axle_side = component_id.split("-")[-2:]
            subsystem = "wheels"
            axle,side=axle_side
            if component_id.startswith("tire-"): component_interfaces=[f"rim-{axle}-{side}"]
            elif component_id.startswith("rim-"): component_interfaces=[f"hub-{axle}-{side}"]
            elif component_id.startswith("hub-"): component_interfaces=[f"{axle}-axle-reference"]
            else: component_interfaces=[f"{axle}-axle-reference","frame-rail-left" if side=="left" else "frame-rail-right"]
        elif "axle-reference" in component_id:
            subsystem = "chassis"
            component_interfaces = [f"{component_id.split('-')[0]}-crossmember"]
        elif "rail" in component_id or "crossmember" in component_id:
            subsystem = "chassis"
        elif component_id == "body-envelope":
            subsystem = "body"
            component_interfaces = ["frame-rail-left","frame-rail-right"]
        elif component_id in {"battery-pack-envelope", "traction-motor-envelope", "inverter-envelope", "reduction-drive-envelope"}:
            subsystem = "propulsion"
            component_interfaces = ["frame-rail-left","frame-rail-right"]
        refs = list(VEHICLE_COMPONENT_PARAMETER_DEPENDENCIES.get(component_id, ()))
        item_trace = {key: vehicle_requirement_trace(design, key) for key in refs}
        items.append({"id": component_id, "name": name, "family": family, "role": role, "parent_id": subsystem, "quantity": 1, "dimensions": dimensions, "center_mm": center, "transform": {"translation_mm":center,"rotation_euler_deg":{"x":0,"y":0,"z":0}}, "coordinate_system": "vehicle: X forward, Y left, Z up; mm", "interfaces": component_interfaces, "parameter_refs": refs, "requirement_traceability": item_trace, "geometry_artifact_reference": f"/api/v1/geometry/{component_id}.stl?revision={design.revision}", "generator_version": VEHICLE_GENERATOR_VERSION, "status": "CALCULATED", "description": f"{role}. Conceptual CAD envelope, not a detailed or validated part."})
    subsystems = sorted({item["parent_id"] for item in items})
    return {"schema_version":"1.0", "design_id":design.id, "family":design.family, "revision":design.revision, "generator_version":VEHICLE_GENERATOR_VERSION, "units":"mm", "coordinate_system":"X forward, Y left, Z up; ground Z=0", "source_prompt":design.source_prompt, "source_prompt_sha256":hashlib.sha256(design.source_prompt.encode("utf-8")).hexdigest() if design.source_prompt else None, "requirements":{key:vehicle_requirement_trace(design,key) for key in VehicleParameters.model_fields if key not in {"occupant_source","occupant_evidence","propulsion_source","propulsion_evidence"}}, "assembly":{"id":"vehicle-assembly","component_ids":[item["id"] for item in items]}, "hierarchy":[{"id":name,"parent_id":"vehicle-assembly","kind":"subsystem"} for name in subsystems], "relationships":[{"source":item["id"],"target":interface,"type":"mounting-or-packaging-reference","parameter_refs":sorted(set(item["parameter_refs"]).intersection(next((other["parameter_refs"] for other in items if other["id"]==interface),[])))} for item in items for interface in item["interfaces"]], "components":items, "assumptions":design.assumptions, "unresolved":["Materials, mass, strength, crashworthiness, range/power sizing, suspension kinematics, thermal design, and regulatory compliance are not determined."], "design_status":"CONCEPTUAL_GEOMETRY"}


def vehicle_requirement_trace(design: VehicleDesign, name: str) -> dict:
    p = design.requirements
    if name == "occupant_capacity":
        trace={"canonical_target": f"requirements.{name}", "value": p.occupant_capacity, "unit": "persons", "source": p.occupant_source.lower().replace("_", "-"), "evidence": p.occupant_evidence}
    elif name == "propulsion_type":
        trace={"canonical_target": f"requirements.{name}", "value": p.propulsion_type, "unit": "", "source": p.propulsion_source.lower().replace("_", "-"), "evidence": p.propulsion_evidence}
    elif name == "propulsion_layout":
        trace={"canonical_target": f"requirements.{name}", "value": p.propulsion_layout, "unit": "", "source": "assumed", "evidence": None}
    else:
        field = getattr(p, name)
        trace={"canonical_target": f"requirements.{name}", "value": field.value, "unit": field.unit, "source": field.source.lower().replace("_", "-"), "evidence": field.evidence}
    evidence=trace["evidence"]
    if evidence and design.source_prompt:
        start=design.source_prompt.find(evidence)
        if start>=0: trace["source_span"]={"start":start,"end":start+len(evidence),"text":evidence}
    return trace


def vehicle_calculate(design: VehicleDesign) -> dict:
    p = design.requirements
    l, w = p.overall_length_mm.value, p.overall_width_mm.value
    tire_r = p.tire_outer_diameter_mm.value / 2
    front_x, rear_x = p.wheelbase_mm.value/2, -p.wheelbase_mm.value/2
    front_y, rear_y = p.front_track_mm.value/2, -p.rear_track_mm.value/2
    wheel_centers = [
        {"id": f"{axle}-{side}", "x_mm": x, "y_mm": y, "z_mm": tire_r}
        for axle, x, track in (("front",front_x,p.front_track_mm.value),("rear",rear_x,p.rear_track_mm.value))
        for side,y in (("left",track/2),("right",-track/2))
    ]
    manifest = vehicle_manifest(design)
    solids=vehicle_component_solids(design)
    bounds=[solid.val().BoundingBox() for solid in solids.values()]
    actual={"length":max(b.xmax for b in bounds)-min(b.xmin for b in bounds),"width":max(b.ymax for b in bounds)-min(b.ymin for b in bounds),"height":max(b.zmax for b in bounds)-min(b.zmin for b in bounds)}
    expected_ids=set(COMPONENT_INFO)
    geometry_validity=all(solid.val().isValid() and solid.val().Volume()>0 for solid in solids.values())
    identities_valid=set(solids)==expected_ids and len(solids)==len(expected_ids)
    within_envelope=(actual["length"]<=l+0.1 and actual["width"]<=w+0.1 and actual["height"]<=p.body_height_mm.value+0.1)
    placements_valid=True
    placement_evidence=[]
    manifest_by_id={item["id"]:item for item in manifest["components"]}
    for wheel in wheel_centers:
        component_id=f"tire-{wheel['id']}"
        center=manifest_by_id[component_id]["center_mm"]
        expected=(wheel["x_mm"],wheel["y_mm"],wheel["z_mm"])
        actual_center=(center["x_mm"],center["y_mm"],center["z_mm"])
        valid=all(math.isclose(a,e,abs_tol=0.05) for a,e in zip(actual_center,expected))
        placements_valid &= valid
        placement_evidence.append(f"{component_id}: expected center {expected} mm; CAD bounding-box center {actual_center} mm; {'matched' if valid else 'mismatch'}.")
    return {
        "overall_length_mm":l,"overall_width_mm":w,"target_range_km":{"value":p.target_range_km.value,"status":"UNRESOLVED","meaning":"User target, not a calculated range"},
        "wheelbase_mm":p.wheelbase_mm.value,"front_track_mm":p.front_track_mm.value,"rear_track_mm":p.rear_track_mm.value,
        "wheel_centers":wheel_centers,"component_count":len(manifest["components"]),"components":[{**item,"outer_diameter_mm": max(item["dimensions"].values())} for item in manifest["components"]],
        "geometry_bounds_mm":actual,
        "geometry_integrity":{"valid_solids":geometry_validity,"stable_component_identities":identities_valid,"expected_component_count":len(expected_ids),"generated_component_count":len(solids)},
        "calculation_status":{"dimensional_consistency":"CALCULATED" if within_envelope else "FAILED","wheel_positions":"CALCULATED" if placements_valid else "FAILED","component_geometry":"CALCULATED" if geometry_validity and identities_valid else "FAILED","range":"UNRESOLVED","mass":"UNRESOLVED","strength":"UNSUPPORTED","safety":"UNSUPPORTED"},
        "clearance_check":{"status":"CALCULATED","ground_clearance_mm":p.ground_clearance_mm.value,"tire_radius_mm":tire_r,"wheel_centers_above_ground":all(item["z_mm"]>0 for item in wheel_centers)},
    }


def vehicle_verification(design: VehicleDesign) -> dict:
    """Evidence for generated envelope relationships; not mechanical-fit/safety proof."""
    from .verification import VerificationItem, VerificationState

    result=vehicle_calculate(design)
    p=design.requirements
    components=result["components"]
    by_id={item["id"]:item for item in components}
    expected_ids=set(COMPONENT_INFO)
    actual_ids=set(by_id)
    bounds=result["geometry_bounds_mm"]
    within=(bounds["length"]<=p.overall_length_mm.value+0.1 and bounds["width"]<=p.overall_width_mm.value+0.1 and bounds["height"]<=p.body_height_mm.value+0.1)
    wheel_evidence=[]
    wheel_ok=True
    for center in result["wheel_centers"]:
        cid=f"tire-{center['id']}"
        mesh_center=by_id[cid]["center_mm"]
        expected_center=(center["x_mm"],center["y_mm"],center["z_mm"])
        actual_center=(mesh_center["x_mm"],mesh_center["y_mm"],mesh_center["z_mm"])
        matched=all(math.isclose(a,e,abs_tol=0.05) for a,e in zip(actual_center,expected_center))
        wheel_ok &= matched
        wheel_evidence.append(f"{cid}: expected CAD center {expected_center} mm; measured {actual_center} mm; {'matched' if matched else 'mismatch'}.")
    axle_ok=True
    for axle in ("front","rear"):
        bbox=vehicle_component_solids(design)[f"{axle}-axle-reference"].val().BoundingBox()
        measured=((bbox.xmin+bbox.xmax)/2,(bbox.ymin+bbox.ymax)/2,(bbox.zmin+bbox.zmax)/2)
        expected_center=(p.wheelbase_mm.value/2 if axle=="front" else -p.wheelbase_mm.value/2,0,p.tire_outer_diameter_mm.value/2)
        matched=all(math.isclose(a,e,abs_tol=0.05) for a,e in zip(measured,expected_center))
        axle_ok &= matched
        wheel_evidence.append(f"{axle}-axle-reference: expected center {expected_center} mm; measured {measured} mm; {'matched' if matched else 'mismatch'}.")
    expected_frame_length=round(p.wheelbase_mm.value*0.92,4)
    frame_dims_ok=all(math.isclose(by_id[cid]["dimensions"]["length_mm"],expected_frame_length,abs_tol=0.05) and math.isclose(by_id[cid]["dimensions"]["width_mm"],p.frame_rail_width_mm.value,abs_tol=0.05) and math.isclose(by_id[cid]["dimensions"]["height_mm"],p.frame_rail_height_mm.value,abs_tol=0.05) for cid in ("frame-rail-left","frame-rail-right"))
    integrity=result["geometry_integrity"]
    geometry_ok=actual_ids==expected_ids and integrity["valid_solids"] and integrity["stable_component_identities"] and result["component_count"]==len(expected_ids) and all(item["status"]=="CALCULATED" and all(math.isfinite(v) and v>0 for v in item["dimensions"].values()) for item in components)
    interface_refs=[(item["id"],target) for item in components for target in item["interfaces"]]
    missing_refs=[f"{source} -> {target}" for source,target in interface_refs if target not in actual_ids]
    known_requirements=set(VehicleParameters.model_fields)-{"occupant_source","occupant_evidence","propulsion_source","propulsion_evidence"}
    traceability_ok=all(item["parameter_refs"] and set(item["parameter_refs"]).issubset(known_requirements) and set(item["parameter_refs"])==set(item["requirement_traceability"]) for item in components)
    return {
        "schema_validation":VerificationItem(state=VerificationState.PASSED,summary="The typed EV parameter schema and cross-field envelope constraints passed.",evidence=["VehicleParameters validation completed before geometry generation."]),
        "component_geometry":VerificationItem(state=VerificationState.PASSED if geometry_ok else VerificationState.FAILED,summary="All required stable component identities map to finite, positive CAD bounding dimensions.",evidence=[f"Expected {len(expected_ids)} unique component IDs; generated {result['component_count']}.","All generated CadQuery solids are checked for Open CASCADE validity and positive volume."]),
        "wheel_axle_placement":VerificationItem(state=VerificationState.PASSED if wheel_ok and axle_ok else VerificationState.FAILED,summary="Wheel/tire and axle-reference centers are compared to coordinates derived from wheelbase, tracks and tire diameter.",evidence=wheel_evidence),
        "frame_dimensions":VerificationItem(state=VerificationState.PASSED if frame_dims_ok else VerificationState.FAILED,summary="Longitudinal rail CAD bounds are compared with wheelbase-scaled length and declared rail cross-section.",evidence=[f"Expected rail length {expected_frame_length:g} mm; expected section {p.frame_rail_width_mm.value:g} x {p.frame_rail_height_mm.value:g} mm.",f"Measured left rail dimensions {by_id['frame-rail-left']['dimensions']}; right rail dimensions {by_id['frame-rail-right']['dimensions']}."]),
        "overall_envelope_containment":VerificationItem(state=VerificationState.PASSED if within else VerificationState.FAILED,summary="Actual assembly CAD bounds must remain within the declared overall length, width and body-height envelopes.",evidence=[f"CAD bounds {bounds}; declared maximum envelope {p.overall_length_mm.value:g} x {p.overall_width_mm.value:g} x {p.body_height_mm.value:g} mm."]),
        "requirement_component_traceability":VerificationItem(state=VerificationState.PASSED if traceability_ok else VerificationState.FAILED,summary="Generated component references resolve to canonical project requirements and include source/provenance values.",evidence=[f"{sum(len(item['parameter_refs']) for item in components)} component-to-requirement links checked across {len(components)} generated CAD components.",f"Original prompt {'stored and SHA-256 identified' if design.source_prompt else 'not supplied for this design'}."]),
        "mechanical_interfaces":VerificationItem(state=VerificationState.PARTIAL if not missing_refs else VerificationState.FAILED,summary="Manifest interface targets are checked for assembly identity; fit, contact, load transfer and kinematics are not modeled.",evidence=[f"Resolved {len(interface_refs)-len(missing_refs)} of {len(interface_refs)} interface references against stable component IDs.",*(missing_refs or ["Wheel/axle coordinates and package/frame references resolve; physical fit and interference remain untested."])]),
        "range_sizing":VerificationItem(state=VerificationState.UNKNOWN,summary="Target range is an input target; energy use and battery sizing are not calculated.",evidence=[f"User target {p.target_range_km.value:g} km; no energy or drive-cycle model exists."]),
        "strength_safety":VerificationItem(state=VerificationState.UNKNOWN,summary="Structural, crash, road-safety, manufacturing, and regulatory performance are unsupported by the implemented models.",evidence=["No relevant analysis or acceptance criteria are implemented."]),
    }


def propagate_vehicle_edits(design: VehicleDesign, changes: dict[str, float]) -> tuple[VehicleDesign, dict[str, list[str]]]:
    """Apply explicit edits and documented overall-envelope dependencies to a copy."""
    candidate=design.model_copy(deep=True)
    propagated: dict[str,list[str]]={}
    req=candidate.requirements
    before_length=req.overall_length_mm.value
    before_width=req.overall_width_mm.value
    for name,value in changes.items():
        sourced=getattr(req,name)
        sourced.value=value
        sourced.source="USER_PROVIDED"
        sourced.evidence=f"Edited in Studio against revision {design.revision}."

    if "overall_length_mm" in changes:
        new_length=changes["overall_length_mm"]
        if "body_length_mm" in changes and not math.isclose(changes["body_length_mm"],new_length,abs_tol=0.001):
            raise ValueError("When editing overall_length_mm and body_length_mm together, their values must match; the body envelope defines the generated overall-length box.")
        if "body_length_mm" not in changes:
            req.body_length_mm= SourcedValue(value=new_length,unit="mm",source="ASSUMED",evidence="Propagated from overall_length_mm; the body envelope tracks the overall length on an EV dimension edit.")
            propagated["overall_length_mm"]=["body_length_mm"]
        if req.wheelbase_mm.source=="ASSUMED":
            propagated.setdefault("overall_length_mm",[])
            req.wheelbase_mm.value=round(req.wheelbase_mm.value*new_length/before_length,3)
            req.wheelbase_mm.evidence="Propagated proportionally from overall_length_mm; wheelbase was an assumed packaging default."
            propagated["overall_length_mm"].append("wheelbase_mm (assumed value scaled proportionally)")
    if "overall_width_mm" in changes:
        new_width=changes["overall_width_mm"]
        assumed_tracks=[req.front_track_mm.source=="ASSUMED",req.rear_track_mm.source=="ASSUMED"]
        if any(assumed_tracks):
            old_max=max(req.front_track_mm.value,req.rear_track_mm.value)
            target_max=new_width-req.tire_width_mm.value
            if target_max<=0:
                raise ValueError("Overall width leaves no space for the tire envelopes.")
            factor=target_max/old_max
            for name,is_assumed in (("front_track_mm",assumed_tracks[0]),("rear_track_mm",assumed_tracks[1])):
                if is_assumed:
                    getattr(req,name).value=round(getattr(req,name).value*factor,3)
                    getattr(req,name).evidence="Propagated proportionally from overall_width_mm; track was an assumed packaging default."
                    propagated.setdefault("overall_width_mm",[]).append(f"{name} (assumed value scaled proportionally)")
        if req.body_width_mm.source=="ASSUMED":
            limiting_width=min(req.front_track_mm.value,req.rear_track_mm.value)-req.tire_width_mm.value
            target_body_width=min(new_width*0.70,limiting_width)
            if target_body_width<=800:
                raise ValueError("Overall width cannot preserve the minimum body-envelope width and tire clearance.")
            req.body_width_mm.value=round(target_body_width,3)
            req.body_width_mm.evidence="Propagated from overall_width_mm while preserving the tire/body package clearance rule."
            propagated.setdefault("overall_width_mm",[]).append("body_width_mm (assumed envelope resized to preserve clearance)")
        elif before_width != new_width and not propagated.get("overall_width_mm") and not any(name in changes for name in ("front_track_mm","rear_track_mm","body_width_mm")):
            raise ValueError("Overall width has no editable dependent geometry: update body_width_mm or an assumed track value in the same request.")
    elif "tire_width_mm" in changes:
        assumed_tracks=[req.front_track_mm.source=="ASSUMED",req.rear_track_mm.source=="ASSUMED"]
        if any(assumed_tracks):
            old_max=max(req.front_track_mm.value,req.rear_track_mm.value)
            target_max=req.overall_width_mm.value-req.tire_width_mm.value
            if target_max<=0:
                raise ValueError("Tire width leaves no space within the overall width envelope.")
            factor=target_max/old_max
            for name,is_assumed in (("front_track_mm",assumed_tracks[0]),("rear_track_mm",assumed_tracks[1])):
                if is_assumed:
                    getattr(req,name).value=round(getattr(req,name).value*factor,3)
                    getattr(req,name).evidence="Propagated from tire_width_mm; track was an assumed packaging default and was moved to preserve the overall width envelope."
                    propagated.setdefault("tire_width_mm",[]).append(f"{name} (assumed value scaled to preserve outer width)")
        limiting_body_width=min(req.front_track_mm.value,req.rear_track_mm.value)-req.tire_width_mm.value
        if req.body_width_mm.source=="ASSUMED" and req.body_width_mm.value>limiting_body_width:
            if limiting_body_width<=800:
                raise ValueError("Tire width leaves insufficient inner clearance for the minimum body envelope width.")
            req.body_width_mm.value=round(limiting_body_width,3)
            req.body_width_mm.evidence="Reduced from the assumed value to preserve the body-to-tire envelope clearance rule."
            propagated.setdefault("tire_width_mm",[]).append("body_width_mm (assumed envelope narrowed to preserve clearance)")

    # Drop outdated assumption statements and regenerate them from the candidate's
    # current provenance for edited and propagated geometry fields.
    affected=set(changes)
    for values in propagated.values():
        affected.update(name.split(" ")[0] for name in values)
    candidate.assumptions=[line for line in candidate.assumptions if not any(line.startswith(f"{name}=") for name in affected)]
    for name in affected:
        if name not in VehicleParameters.model_fields:
            continue
        value=getattr(req,name)
        if isinstance(value,SourcedValue) and value.source=="ASSUMED":
            candidate.assumptions.append(f"{name}={value.value:g} {value.unit} is an assumed, propagated conceptual-geometry value.")
    candidate.revision=design.revision+1
    candidate.updated_at=datetime.now(timezone.utc).isoformat()
    candidate.history=[*design.history,{"revision":design.revision,"changed_at":design.updated_at,"design":design.model_dump(mode="json")}]
    candidate=VehicleDesign.model_validate(candidate.model_dump(mode="json"))
    return candidate,propagated


def export_vehicle_component_stl(design: VehicleDesign, component_id: str, target: Path) -> None:
    solids = vehicle_component_solids(design)
    if component_id not in solids:
        raise KeyError(f"Unknown vehicle component '{component_id}'.")
    with VEHICLE_CAD_LOCK:
        solids[component_id].val().exportStl(str(target), tolerance=0.5, angularTolerance=0.2, ascii=False, relative=True, parallel=False)


def export_vehicle_stl(design: VehicleDesign, target: Path) -> None:
    with VEHICLE_CAD_LOCK:
        assembly = build_vehicle_assembly(design)
        assembly.toCompound().exportStl(str(target), tolerance=0.5, angularTolerance=0.2, ascii=False, relative=True, parallel=False)


def build_vehicle_assembly(design: VehicleDesign) -> cq.Assembly:
    assembly = cq.Assembly(name=f"electric_vehicle_r{design.revision}")
    for component_id, solid in vehicle_component_solids(design).items():
        assembly.add(solid, name=component_id, color=cq.Color(0.08,0.48,0.62) if "tire" not in component_id else cq.Color(0.16,0.18,0.2))
    return assembly


def export_vehicle_step(design: VehicleDesign, target: Path) -> None:
    with VEHICLE_CAD_LOCK:
        build_vehicle_assembly(design).export(str(target), exportType="STEP")


def vehicle_bom(design: VehicleDesign) -> dict:
    manifest = vehicle_manifest(design)
    return {"schema_version":"1.0", "design_id":design.id, "revision":design.revision, "units":"mm", "items":[{"component_id":item["id"],"description":item["name"],"family":item["family"],"quantity":item["quantity"],"dimensions":item["dimensions"],"parameter_refs":item["parameter_refs"],"requirement_traceability":item["requirement_traceability"],"material":None,"mass_kg":None,"cost":None,"status":item["status"]} for item in manifest["components"]],"note":"Quantities and bounding dimensions describe generated conceptual geometry; material, mass, cost, and manufacturing data are unknown."}


def export_vehicle_drawing_pdf(design: VehicleDesign, target: Path) -> None:
    """Create top/side/front vector projections from the canonical envelope geometry."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A3, landscape
    from reportlab.pdfgen import canvas

    p = design.requirements
    page_w, page_h = landscape(A3)
    c = canvas.Canvas(str(target), pagesize=(page_w,page_h), pageCompression=1)
    c.setTitle(f"AeroPKmech EV layout R{design.revision}")
    c.setFont("Helvetica-Bold",18); c.drawString(36,page_h-40,"Concept EV packaging layout")
    c.setFont("Helvetica",10); c.drawString(36,page_h-58,f"Design {design.id} · revision {design.revision} · all dimensions mm · scale 1:20")
    scale=0.05
    solids=vehicle_component_solids(design)
    manifest=vehicle_manifest(design)
    def project_box(component_id, x0, y0, axes, fill=colors.HexColor("#dceaf0")):
        solid=solids[component_id].val().BoundingBox()
        if axes=="top": a0,a1,b0,b1=solid.xmin,solid.xmax,solid.ymin,solid.ymax; px=x0+(a0+p.overall_length_mm.value/2)*scale; py=y0+(b0+p.overall_width_mm.value/2)*scale
        elif axes=="side": a0,a1,b0,b1=solid.xmin,solid.xmax,solid.zmin,solid.zmax; px=x0+(a0+p.overall_length_mm.value/2)*scale; py=y0+b0*scale
        else: a0,a1,b0,b1=solid.ymin,solid.ymax,solid.zmin,solid.zmax; px=x0+(a0+p.overall_width_mm.value/2)*scale; py=y0+b0*scale
        c.setFillColor(fill); c.setStrokeColor(colors.HexColor("#35566a")); c.rect(px,py,(a1-a0)*scale,(b1-b0)*scale,fill=1,stroke=1)
    # Top view from canonical individual solids.
    top=(45,420); side=(45,180); front=(520,420)
    for view,origin in (("TOP",top),("SIDE",side),("FRONT",front)):
        c.setFont("Helvetica-Bold",12);c.drawString(*origin,view+" PROJECTION")
    ty=top[1]-170
    for item in manifest["components"]:
        cid=item["id"]
        if cid.startswith("tire-") or cid.startswith("rim-") or cid.startswith("hub-") or cid.startswith("suspension-") or "axle" in cid or "rail" in cid or "crossmember" in cid or cid in {"body-envelope","battery-pack-envelope","inverter-envelope","reduction-drive-envelope"}:
            project_box(cid,top[0]+18,ty,"top",colors.HexColor("#cadfe7") if "tire" not in cid else colors.HexColor("#79858b"))
    sx,sy=side[0]+18,side[1]-85
    for cid in ("frame-rail-left","frame-rail-right","body-envelope","battery-pack-envelope","traction-motor-envelope","inverter-envelope","reduction-drive-envelope"):
        project_box(cid,sx,sy,"side")
    fx,fy=front[0]+18,front[1]-110
    for cid in ("body-envelope","frame-rail-left","frame-rail-right","tire-front-left","tire-front-right"):
        project_box(cid,fx,fy,"front",colors.HexColor("#cadfe7") if "tire" not in cid else colors.HexColor("#79858b"))
    c.setStrokeColor(colors.black);c.setFillColor(colors.black);c.setFont("Helvetica",9)
    overall_x0,overall_x1=top[0]+18,top[0]+18+p.overall_length_mm.value*scale
    overall_y0=top[1]-170
    c.setStrokeColor(colors.HexColor("#35566a"));c.setFillColor(colors.HexColor("#243b4b"))
    c.line(overall_x0,overall_y0-8,overall_x1,overall_y0-8)
    c.line(overall_x0,overall_y0-12,overall_x0,overall_y0+2);c.line(overall_x1,overall_y0-12,overall_x1,overall_y0+2)
    c.line(top[0]+8,overall_y0,top[0]+8,overall_y0+p.overall_width_mm.value*scale)
    c.line(top[0]+4,overall_y0,top[0]+18,overall_y0);c.line(top[0]+4,overall_y0+p.overall_width_mm.value*scale,top[0]+18,overall_y0+p.overall_width_mm.value*scale)
    c.setFillColor(colors.black);c.drawCentredString((overall_x0+overall_x1)/2,overall_y0-22,f"{p.overall_length_mm.value:.0f} mm")
    c.saveState();c.translate(top[0]-2,overall_y0+p.overall_width_mm.value*scale/2);c.rotate(90);c.drawCentredString(0,0,f"{p.overall_width_mm.value:.0f} mm");c.restoreState()
    c.setStrokeColor(colors.black);c.line(900,55,950,55);c.line(900,51,900,59);c.line(950,51,950,59);c.drawCentredString(925,42,"1000 mm at 1:20")
    c.drawString(top[0],top[1]-200,f"Overall length {p.overall_length_mm.value:.0f} mm ({p.overall_length_mm.source.lower()})")
    c.drawString(top[0],top[1]-214,f"Overall width {p.overall_width_mm.value:.0f} mm ({p.overall_width_mm.source.lower()})")
    c.drawString(top[0],top[1]-228,f"Wheelbase {p.wheelbase_mm.value:.0f} mm ({p.wheelbase_mm.source.lower()}); front/rear track {p.front_track_mm.value:.0f}/{p.rear_track_mm.value:.0f} mm ({p.front_track_mm.source.lower()})")
    c.drawString(36,42,"CONCEPTUAL ENVELOPES ONLY · no structural, crash, range, safety, or manufacturing validation · dimensions shown are source-tagged inputs/defaults")
    c.save()
