"""Shared, family-neutral identities for canonical design parameters."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .quantities import EngineeringQuantity


class ParameterRecord(BaseModel):
    """Revision-bound parameter identity shared by the implemented families.

    `id` is stable across revisions; `revision` identifies the exact value and
    provenance snapshot. Component and source parameter references are checked
    by the containing family model, where the valid IDs are known.
    """

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    id: str = Field(min_length=3, max_length=240)
    project_id: str = Field(min_length=1, max_length=120)
    family_id: str = Field(min_length=1, max_length=80)
    revision: int = Field(ge=1)
    path: str = Field(min_length=1, max_length=120)
    component_ids: list[str] = Field(default_factory=list)
    quantity: EngineeringQuantity
    source_parameter_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def stable_identity(self) -> "ParameterRecord":
        expected_id = f"{self.project_id}:{self.path}"
        if self.id != expected_id:
            raise ValueError("Parameter record ID must be the stable project ID plus canonical path.")
        if len(self.source_parameter_ids) != len(set(self.source_parameter_ids)):
            raise ValueError("Parameter source references must be unique.")
        if self.id in self.source_parameter_ids:
            raise ValueError("Parameter records cannot derive from themselves.")
        return self


def build_parameter_records(
    *, project_id: str, family_id: str, revision: int,
    quantities: dict[str, EngineeringQuantity],
    component_ids: set[str],
    component_paths: dict[str, list[str]] | None = None,
    derivations: dict[str, list[str]] | None = None,
) -> dict[str, ParameterRecord]:
    """Build and validate stable records from a family's canonical quantities."""
    component_paths = component_paths or {}
    derivations = derivations or {}
    records: dict[str, ParameterRecord] = {}
    for path, quantity in quantities.items():
        related_components = component_paths.get(path, [])
        if len(related_components) != len(set(related_components)):
            raise ValueError(f"Parameter {path} contains duplicate component references.")
        missing_components = set(related_components) - component_ids
        if missing_components:
            raise ValueError(f"Parameter {path} references missing components: {sorted(missing_components)}.")
        parameter_id = f"{project_id}:{path}"
        records[path] = ParameterRecord(
            id=parameter_id,
            project_id=project_id,
            family_id=family_id,
            revision=revision,
            path=path,
            component_ids=related_components,
            quantity=quantity,
            source_parameter_ids=[f"{project_id}:{source}" for source in derivations.get(path, [])],
        )
    for path, record in records.items():
        unknown = set(record.source_parameter_ids) - {item.id for item in records.values()}
        if unknown:
            raise ValueError(f"Parameter {path} references missing source parameters: {sorted(unknown)}.")
    return records


def validate_parameter_records(
    saved: dict[str, ParameterRecord], expected: dict[str, ParameterRecord],
) -> None:
    if set(saved) != set(expected):
        raise ValueError("Persisted parameter record map is incomplete or contains unknown fields.")
    for path, record in expected.items():
        if saved[path] != record:
            raise ValueError(f"Persisted parameter record for {path} is inconsistent with canonical state.")
