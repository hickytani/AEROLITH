"""Bounded requirement extraction for one supported family.

This deterministic extractor is a safe baseline, not a language model. A future
provider may propose the same schema, but every provider result must validate
against the contract and remain an uncommitted proposal until user review.
"""
from __future__ import annotations

import re
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


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
