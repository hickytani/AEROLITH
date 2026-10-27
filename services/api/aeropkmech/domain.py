from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import ParameterRecord, build_parameter_records, validate_parameter_records
from .quantities import EngineeringQuantity, QuantityKind, quantity_from_canonical


class Requirements(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    gear_ratio: float = Field(gt=0)
    input_torque_Nm: float = Field(gt=0)
    input_speed_rpm: float = Field(gt=0)
    module_mm: float = Field(ge=0.5, le=6)
    face_width_mm: float = Field(ge=2, le=60)
    pressure_angle_deg: float = Field(default=20, ge=14, le=30)
    # Optional mounting hub extension (shaft hub protruding beyond the gear face)
    hub_diameter_mm: float | None = Field(default=None, ge=4, le=60,
        description="Outside diameter of the cylindrical shaft hub (mm). Must exceed computed bore diameter.")
    hub_length_mm: float | None = Field(default=None, ge=2, le=60,
        description="Axial length of the shaft hub extension beyond one gear face (mm).")


class Component(BaseModel):
    id: Literal["pinion", "gear"]
    name: str
    teeth: int = Field(ge=8, le=120)
    visible: bool = True


class Design(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = "demo-gearbox"
    family: Literal["spur_gear_pair"] = "spur_gear_pair"
    schema_version: Literal["1.0"] = "1.0"
    revision: int = Field(ge=1)
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    requirements: Requirements
    assumptions: list[str]
    components: list[Component]
    status: dict[str, str]
    source_prompt: str | None = Field(default=None, max_length=4000)
    requirement_sources: dict[str, Literal["user-provided", "derived", "assumed", "missing"]] = Field(default_factory=dict)
    requirement_evidence: dict[str, str] = Field(default_factory=dict)
    parameter_quantities: dict[str, EngineeringQuantity] = Field(default_factory=dict)
    parameter_records: dict[str, ParameterRecord] = Field(default_factory=dict)
    history: list[dict] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_pair(self) -> "Design":
        if len(self.components) != 2 or [c.id for c in self.components] != ["pinion", "gear"]:
            raise ValueError("Design must contain one pinion followed by one driven gear.")
        if self.components[0].teeth > 80:
            raise ValueError("Pinion teeth must be no greater than 80.")
        expected = self.components[1].teeth / self.components[0].teeth
        if abs(expected - self.requirements.gear_ratio) > 1e-9:
            raise ValueError("Gear ratio must equal driven gear teeth divided by pinion teeth.")
        allowed = set(Requirements.model_fields) | {"pinion_teeth", "gear_teeth"}
        if not set(self.requirement_sources) <= allowed or not set(self.requirement_evidence) <= allowed:
            raise ValueError("Requirement provenance contains an unsupported parameter name.")
        for key, evidence in self.requirement_evidence.items():
            if not evidence or not self.source_prompt or evidence not in self.source_prompt:
                raise ValueError(f"Requirement evidence for {key} must be an exact span of the retained source prompt.")
        # Hub cross-field constraint: hub outside diameter must exceed computed bore to produce a valid solid
        if self.requirements.hub_diameter_mm is not None:
            min_teeth = min(c.teeth for c in self.components)
            bore_d = min(max(self.requirements.module_mm * 2, 4.0), self.requirements.module_mm * (min_teeth - 2.5) * 0.7)
            if self.requirements.hub_diameter_mm <= bore_d:
                raise ValueError(
                    f"hub_diameter_mm ({self.requirements.hub_diameter_mm:.2f}) must exceed computed bore diameter"
                    f" ({bore_d:.2f} mm). Increase hub_diameter_mm or reduce module_mm."
                )
        quantity_specs: dict[str, tuple[float, str, QuantityKind, float | None, float | None]] = {
            "pinion_teeth": (self.components[0].teeth, "teeth", "count", 8, 80),
            "gear_teeth": (self.components[1].teeth, "teeth", "count", 8, 120),
            "gear_ratio": (self.requirements.gear_ratio, "ratio", "ratio", 0, None),
            "input_torque_Nm": (self.requirements.input_torque_Nm, "N\u00b7m", "torque", 0, None),
            "input_speed_rpm": (self.requirements.input_speed_rpm, "rpm", "rotational_speed", 0, None),
            "module_mm": (self.requirements.module_mm, "mm", "length", 0.5, 6),
            "face_width_mm": (self.requirements.face_width_mm, "mm", "length", 2, 60),
            "pressure_angle_deg": (self.requirements.pressure_angle_deg, "deg", "angle", 14, 30),
        }
        if self.requirements.hub_diameter_mm is not None:
            quantity_specs["hub_diameter_mm"] = (self.requirements.hub_diameter_mm, "mm", "length", 4, 60)
        if self.requirements.hub_length_mm is not None:
            quantity_specs["hub_length_mm"] = (self.requirements.hub_length_mm, "mm", "length", 2, 60)
        expected_quantities = {}

        for name, (value, unit, kind, minimum, maximum) in quantity_specs.items():
            source = self.requirement_sources.get(name, "derived" if name == "gear_ratio" else "assumed")
            evidence = self.requirement_evidence.get(name)
            span = None
            if evidence and self.source_prompt:
                start = self.source_prompt.find(evidence)
                if start >= 0:
                    span = {"start": start, "end": start + len(evidence), "text": evidence}
            expected_quantities[name] = quantity_from_canonical(
                value, unit, kind, source, evidence=evidence, source_span=span,
                derivation="gear_teeth / pinion_teeth" if name == "gear_ratio" and source == "derived" else None,
                minimum=minimum, maximum=maximum,
            )
        if not self.parameter_quantities:
            self.parameter_quantities = expected_quantities
        else:
            if set(self.parameter_quantities) != set(expected_quantities):
                raise ValueError("Persisted parameter quantity map is incomplete or contains unknown fields.")
            for name, expected in expected_quantities.items():
                saved = self.parameter_quantities[name]
                if (saved.value != expected.value or saved.canonical_unit != expected.canonical_unit
                    or saved.quantity_kind != expected.quantity_kind or saved.source != expected.source
                    or saved.evidence != expected.evidence or saved.source_span != expected.source_span):
                    raise ValueError(f"Persisted quantity contract for {name} does not match canonical design state.")
        expected_records = build_parameter_records(
            project_id=self.id, family_id=self.family, revision=self.revision,
            quantities=expected_quantities, component_ids={item.id for item in self.components},
            component_paths={"pinion_teeth": ["pinion"], "gear_teeth": ["gear"]},
            derivations={"gear_ratio": ["gear_teeth", "pinion_teeth"]},
        )
        if not self.parameter_records:
            self.parameter_records = expected_records
        else:
            validate_parameter_records(self.parameter_records, expected_records)
        return self


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    expected_revision: int | None = Field(default=None, ge=1)
    source_prompt: str | None = Field(default=None, max_length=4000)
    requirement_sources: dict[str, Literal["user-provided", "derived", "assumed", "missing"]] = Field(default_factory=dict)
    requirement_evidence: dict[str, str] = Field(default_factory=dict)
    pinion_teeth: int | None = Field(default=None, ge=8, le=80)
    gear_teeth: int | None = Field(default=None, ge=8, le=120)
    input_torque_Nm: float | None = Field(default=None, gt=0)
    input_speed_rpm: float | None = Field(default=None, gt=0)
    module_mm: float | None = Field(default=None, ge=0.5, le=6)
    face_width_mm: float | None = Field(default=None, ge=2, le=60)
    pressure_angle_deg: float | None = Field(default=None, ge=14, le=30)
    hub_diameter_mm: float | None = Field(default=None, ge=4, le=60)
    hub_length_mm: float | None = Field(default=None, ge=2, le=60)

    @model_validator(mode="after")
    def at_least_one_edit(self) -> "EditRequest":
        if not self.model_dump(exclude_none=True, exclude={"expected_revision", "source_prompt", "requirement_sources", "requirement_evidence"}):
            raise ValueError("At least one design field must be provided.")
        allowed = set(Requirements.model_fields) | {"pinion_teeth", "gear_teeth"}
        if not set(self.requirement_sources) <= allowed or not set(self.requirement_evidence) <= allowed:
            raise ValueError("Requirement provenance contains an unsupported parameter name.")
        for key, evidence in self.requirement_evidence.items():
            if not evidence or not self.source_prompt or evidence not in self.source_prompt:
                raise ValueError(f"Requirement evidence for {key} must be an exact span of source_prompt.")
        return self


class InterpretRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)
