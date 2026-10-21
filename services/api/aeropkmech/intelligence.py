"""Bounded requirement extraction for one supported family.

This deterministic extractor is a safe baseline, not a language model. A future
provider may propose the same schema, but every provider result must validate
against the contract and remain an uncommitted proposal until user review.
"""
from __future__ import annotations

import re
from typing import Literal
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ProposedRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    pinion_teeth: int | None = Field(default=None, ge=8, le=80)
    gear_teeth: int | None = Field(default=None, ge=8, le=120)
    gear_ratio: float | None = Field(default=None, gt=0)
    input_torque_Nm: float | None = Field(default=None, gt=0)
    input_speed_rpm: float | None = Field(default=None, gt=0)
    module_mm: float | None = Field(default=None, ge=0.5, le=6)
    face_width_mm: float | None = Field(default=None, ge=2, le=60)


class Extraction(BaseModel):
    family: str = "spur_gear_pair"
    provider: str
    parsed: bool
    proposal: ProposedRequirements
    missing: list[str]
    conflicts: list[str]
    evidence: dict[str, str]
    requires_confirmation: bool = True


class SpecificationParameter(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str
    meaning: str
    value: int | float | str | None
    unit: str
    source: Literal["user-provided", "derived", "assumed", "missing"]
    evidence: str | None
    status: Literal["PROPOSED", "DERIVED", "ASSUMED", "MISSING", "INVALID"]


class SpecificationComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    kind: Literal["assembly", "subsystem", "component"] = "component"
    parent_id: str | None = None
    role: str
    parameter_refs: list[str]
    status: Literal["PROPOSED", "CONCEPTUAL_ONLY"] = "PROPOSED"
    generator_available: bool = True


class SpecificationConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    source_component: str
    target_component: str
    relationship: str
    parameter_refs: list[str]
    status: Literal["PROPOSED", "NEEDS_INPUT", "CONCEPTUAL_ONLY"]


class EngineeringSpecification(BaseModel):
    """Reviewable, deterministic prompt interpretation; never a committed design."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    provider: str = "deterministic-patterns-v1"
    request: str
    intent: Literal["SUPPORTED_SPUR_GEAR_PAIR", "CONCEPTUAL_ELECTRIC_VEHICLE", "SUPPORTED_ELECTRIC_VEHICLE", "UNSUPPORTED_OR_UNCLEAR"]
    system_name: str
    domain: Literal["mechanical", "automotive", "unknown"]
    generation_status: Literal["SPECIFICATION_REVIEW", "GEOMETRY_REVIEW", "CONCEPTUAL_ONLY", "UNSUPPORTED_OR_UNCLEAR"]
    family_id: str | None
    family_schema_version: str | None
    parameters: list[SpecificationParameter]
    components: list[SpecificationComponent]
    connections: list[SpecificationConnection]
    supported_artifacts: list[str]
    assumptions: list[str]
    limitations: list[str]
    unresolved_questions: list[str]
    conflicts: list[str]
    validation_issues: list[str]
    unsupported_requests: list[str]
    requires_confirmation: Literal[True] = True
    can_commit: bool


class RequirementProvider(Protocol):
    async def propose(self, text: str) -> dict: ...


class NoModelProvider:
    """Placeholder injection boundary; intentionally makes no network call."""


def _match(pattern: str, text: str, group: int = 1) -> tuple[str | None, str | None]:
    found = re.search(pattern, text, flags=re.IGNORECASE)
    if not found:
        return None, None
    return found.group(group), found.group(0)


def extract_local(text: str) -> Extraction:
    evidence: dict[str, str] = {}
    fields: dict[str, int | float | None] = {}

    tooth_patterns = {
        "pinion_teeth": [
            r"(?:pinion|driver)\s*(?:teeth|tooth)?\s*(?:=|:|is)?\s*(\d+)\s*(?:teeth|tooth)?\b",
            r"(\d+)\s*(?:teeth|tooth)\s*(?:pinion|driver)\b",
        ],
        "gear_teeth": [
            r"(?:driven\s+)?gear\s*(?:teeth|tooth)?\s*(?:=|:|is)?\s*(\d+)\s*(?:teeth|tooth)?\b",
            r"(\d+)\s*(?:teeth|tooth)\s+(?:driven\s+)?gear\b",
        ],
    }
    for key, patterns in tooth_patterns.items():
        for pattern in patterns:
            raw, matched = _match(pattern, text)
            if raw is not None:
                fields[key] = int(raw)
                evidence[key] = matched or ""
                break
        else:
            fields[key] = None

    patterns = {
        "gear_ratio": (r"(?:gear\s+)?ratio\s*(?:of|is|=|:)?\s*(\d+(?:\.\d+)?)\s*(?::\s*1)?\b", float),
        "input_torque_Nm": (r"(?:input\s+)?torque\s*(?:of|is|=|:)?\s*(\d+(?:\.\d+)?)\s*(N\s*mm|N\s*[·.]?\s*m|Nm)\b", float),
        "input_speed_rpm": (r"(?:input\s+)?speed\s*(?:of|is|=|:)?\s*(\d+(?:\.\d+)?)\s*rpm\b", float),
        "module_mm": (r"module\s*(?:of|is|=|:)?\s*(\d+(?:\.\d+)?)\s*mm\b", float),
        "face_width_mm": (r"(?:face\s+width|width)\s*(?:of|is|=|:)?\s*(\d+(?:\.\d+)?)\s*mm\b", float),
    }
    for key, (pattern, convert) in patterns.items():
        raw, matched = _match(pattern, text)
        if raw is None:
            fields[key] = None
        else:
            fields[key] = convert(raw)
            evidence[key] = matched or ""
            if key == "input_torque_Nm" and re.search(r"N\s*mm\b", matched or "", re.IGNORECASE):
                fields[key] = float(raw) / 1000

    conflicts: list[str] = []
    if fields["pinion_teeth"] and fields["gear_teeth"]:
        ratio_from_teeth = fields["gear_teeth"] / fields["pinion_teeth"]
        if fields["gear_ratio"] is None:
            fields["gear_ratio"] = ratio_from_teeth
            evidence["gear_ratio"] = "derived from explicitly stated pinion and driven gear tooth counts"
        elif abs(fields["gear_ratio"] - ratio_from_teeth) > 1e-9:
            conflicts.append(
                f"Stated ratio {fields['gear_ratio']:g}:1 conflicts with explicit tooth counts ({ratio_from_teeth:g}:1)."
            )

    try:
        proposal = ProposedRequirements.model_validate(fields)
    except ValidationError as exc:
        # Keep out-of-range values visible as invalid requirements instead of
        # turning the entire interpretation request into an opaque HTTP error.
        for issue in exc.errors():
            name = str(issue["loc"][0])
            value = fields.get(name)
            conflicts.append(f"{name} value {value!r} is outside the supported input range ({issue['msg']}).")
            fields[name] = None
        proposal = ProposedRequirements.model_validate(fields)
    missing = [key for key, value in proposal.model_dump().items() if value is None]
    return Extraction(
        provider="deterministic-patterns-v1",
        parsed=not missing and not conflicts,
        proposal=proposal,
        missing=missing,
        conflicts=conflicts,
        evidence=evidence,
    )


_PARAMETER_INFO = {
    "pinion_teeth": ("Input pinion tooth count", "teeth"),
    "gear_teeth": ("Driven gear tooth count", "teeth"),
    "gear_ratio": ("Driven-to-input tooth ratio", "ratio"),
    "module_mm": ("Gear module", "mm"),
    "face_width_mm": ("Face width", "mm"),
    "input_torque_Nm": ("Input torque", "N·m"),
    "input_speed_rpm": ("Input rotational speed", "rpm"),
}

_GEAR_PAIR_INTENT = re.compile(r"\bspur[ -]gear(?:s)?\b|\bgear pair\b", re.IGNORECASE)
_VEHICLE_INTENT = re.compile(r"\b(car|vehicle|automotive|sports? car|sportscar|SUV)\b", re.IGNORECASE)
_ELECTRIC_INTENT = re.compile(r"\b(electric|EV|battery[ -]electric)\b", re.IGNORECASE)
_UNSUPPORTED_SCOPE = re.compile(
    r"\b(vehicle|car|truck|motorcycle|bicycle|aircraft|airplane|aircraft|uav|drone|rocket|spacecraft|robot|robotics|wing|gearbox|transmission|bearing|shaft|motor|battery|brake|suspension)\b",
    re.IGNORECASE,
)


def propose_specification(text: str) -> EngineeringSpecification:
    """Interpret the delivered gear-pair family or the conceptual EV planner."""
    if _VEHICLE_INTENT.search(text) and _ELECTRIC_INTENT.search(text):
        from .automotive import propose_electric_vehicle

        vehicle = propose_electric_vehicle(text)
        parameters = [SpecificationParameter(
            name=parameter.name,
            meaning=parameter.meaning,
            value=parameter.value,
            unit=parameter.unit,
            source=parameter.source,
            evidence=parameter.evidence,
            status=parameter.status,
        ) for parameter in vehicle.parameters]
        required_names = {"occupant_capacity", "overall_length_mm", "overall_width_mm", "target_range_km", "propulsion_type"}
        supplied = {item.name for item in parameters if item.source == "user-provided" and item.value is not None}
        ready = required_names.issubset(supplied) and not vehicle.validation_issues
        components = [SpecificationComponent(
            id=node.id, name=node.name, kind=node.kind, parent_id=node.parent_id,
            role=node.role, parameter_refs=node.parameter_refs,
            status="PROPOSED" if ready else "CONCEPTUAL_ONLY", generator_available=ready,
        ) for node in vehicle.nodes]
        connections = [SpecificationConnection(
            id=relationship.id, source_component=relationship.source_id,
            target_component=relationship.target_id, relationship=relationship.relationship,
            parameter_refs=[], status="PROPOSED",
        ) for relationship in vehicle.relationships]
        return EngineeringSpecification(
            request=text, intent="SUPPORTED_ELECTRIC_VEHICLE" if ready else "CONCEPTUAL_ELECTRIC_VEHICLE",
            system_name=vehicle.system_name, domain="automotive", generation_status="GEOMETRY_REVIEW" if ready else "CONCEPTUAL_ONLY",
            family_id="electric_vehicle" if ready else None, family_schema_version="1.0" if ready else None, parameters=parameters,
            components=components, connections=connections, supported_artifacts=["STEP", "STL", "component STL", "layout drawing PDF", "manifest JSON", "BOM JSON"] if ready else [],
            assumptions=vehicle.assumptions, limitations=vehicle.limitations,
            unresolved_questions=vehicle.unresolved_questions,
            conflicts=[], validation_issues=vehicle.validation_issues,
            unsupported_requests=[],
            can_commit=ready,
        )

    extraction = extract_local(text)
    scope_mentions = sorted({match.group(0).lower() for match in _UNSUPPORTED_SCOPE.finditer(text)})
    is_supported = bool(_GEAR_PAIR_INTENT.search(text)) and not scope_mentions
    values = extraction.proposal.model_dump()
    validation_issues = [item for item in extraction.conflicts if "outside the supported input range" in item]
    conflicts = [item for item in extraction.conflicts if item not in validation_issues]
    invalid_fields = {field for issue in validation_issues for field in values if issue.startswith(f"{field} value")}

    parameters: list[SpecificationParameter] = []
    for name, (meaning, unit) in _PARAMETER_INFO.items():
        value = values[name]
        is_derived_ratio = (
            name == "gear_ratio"
            and extraction.evidence.get(name, "").startswith("derived from")
        )
        source: Literal["user-provided", "derived", "missing"] = (
            "missing" if value is None else "derived" if is_derived_ratio else "user-provided"
        )
        status: Literal["PROPOSED", "DERIVED", "MISSING", "INVALID"] = (
            "INVALID" if name in invalid_fields else "MISSING" if value is None else "DERIVED" if is_derived_ratio else "PROPOSED"
        )
        parameters.append(SpecificationParameter(
            name=name,
            meaning=meaning,
            value=value,
            unit=unit,
            source=source,
            evidence=extraction.evidence.get(name),
            status=status,
        ))

    supported_requests = []
    if scope_mentions:
        supported_requests.append(
            "The request also names broader or unsupported scope (" + ", ".join(scope_mentions) + "); this release cannot generate those systems."
        )
    if not _GEAR_PAIR_INTENT.search(text):
        supported_requests.append("Only an explicitly described external spur gear pair is supported by this generator.")
    if is_supported:
        components = [
            SpecificationComponent(
                id="gear-pair", name="External spur gear pair", kind="assembly",
                parent_id=None, role="Top-level mechanical assembly",
                parameter_refs=["pinion_teeth", "gear_teeth", "module_mm", "face_width_mm"],
                generator_available=True,
            ),
            SpecificationComponent(id="pinion", name="Pinion", parent_id="gear-pair", role="Input driver", parameter_refs=["pinion_teeth", "module_mm", "face_width_mm"]),
            SpecificationComponent(id="gear", name="Driven gear", parent_id="gear-pair", role="Output driven member", parameter_refs=["gear_teeth", "module_mm", "face_width_mm"]),
        ]
        connections = [SpecificationConnection(
            id="external-gear-mesh",
            source_component="pinion",
            target_component="gear",
            relationship="external_gear_mesh",
            parameter_refs=["pinion_teeth", "gear_teeth", "module_mm"],
            status="PROPOSED" if not extraction.missing else "NEEDS_INPUT",
        )]
        artifacts = ["STEP", "STL", "HTML report", "PDF report", "dimensioned gear reference layout PDF"]
    else:
        components, connections, artifacts = [], [], []

    unresolved = [
        f"Provide {name.replace('_', ' ')}" for name, value in values.items() if value is None
    ]
    assumptions = [
        "The supported family represents one external spur gear pair; no larger vehicle, gearbox, or machine assembly is inferred.",
        "A generated polygonal tooth approximation is educational geometry, not a verified involute or manufacturing profile.",
        "Ideal kinematic calculations do not establish strength, fatigue life, interference-free engagement, thermal performance, safety, or standards compliance.",
        "No material, tolerance, shaft fit, losses, or service environment is assumed by the parser.",
    ] if is_supported else [
        "No design defaults or components were substituted for the unsupported or unclear request."
    ]

    return EngineeringSpecification(
        request=text,
        intent="SUPPORTED_SPUR_GEAR_PAIR" if is_supported else "UNSUPPORTED_OR_UNCLEAR",
        system_name="External spur gear pair" if is_supported else "Unclassified engineering request",
        domain="mechanical" if is_supported else "unknown",
        generation_status="SPECIFICATION_REVIEW" if is_supported else "UNSUPPORTED_OR_UNCLEAR",
        family_id="spur_gear_pair" if is_supported else None,
        family_schema_version="1.0" if is_supported else None,
        parameters=parameters,
        components=components,
        connections=connections,
        supported_artifacts=artifacts,
        assumptions=assumptions,
        limitations=[
            "CAD geometry is an educational polygonal tooth approximation, not involute or manufacturing-ready.",
            "Strength, fatigue, thermal, safety, material, fit, and interference analyses are unsupported.",
        ] if is_supported else ["No supported generator is available for the classified request."],
        unresolved_questions=unresolved,
        conflicts=conflicts,
        validation_issues=validation_issues,
        unsupported_requests=supported_requests,
        can_commit=is_supported and extraction.parsed and not conflicts and not validation_issues,
    )


async def extract(text: str, provider: RequirementProvider | None = None) -> Extraction:
    if provider is None or isinstance(provider, NoModelProvider):
        return extract_local(text)
    # A provider may return only the typed proposal. Pydantic rejects extra
    # fields and invalid ranges; evidence/conflicts are still generated locally.
    candidate = ProposedRequirements.model_validate(await provider.propose(text))
    local = extract_local(text)
    proposed = candidate.model_dump()
    missing = [key for key, value in proposed.items() if value is None]
    return Extraction(
        provider=type(provider).__name__,
        parsed=not missing and not local.conflicts,
        proposal=candidate,
        missing=missing,
        conflicts=local.conflicts,
        evidence=local.evidence,
    )
