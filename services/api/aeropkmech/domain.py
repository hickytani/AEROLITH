from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Requirements(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    gear_ratio: float = Field(gt=0)
    input_torque_Nm: float = Field(gt=0)
    input_speed_rpm: float = Field(gt=0)
    module_mm: float = Field(ge=0.5, le=6)
    face_width_mm: float = Field(ge=2, le=60)


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
