"""Versioned quantities shared by requirement proposals and canonical design state."""
from __future__ import annotations

import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

QUANTITY_SCHEMA_VERSION = "1.0"

QuantityKind = Literal["length", "range", "angle", "torque", "rotational_speed", "ratio", "count"]
QuantitySource = Literal["user-provided", "assumed", "derived", "missing"]

# canonical unit and multiplier from accepted input unit
_UNIT_DEFINITIONS: dict[str, tuple[str, str, float]] = {}


def _unit_key(unit: str) -> str:
    raw = unit.strip().lower().replace("â", "").replace("Â", "")
    if raw in {"°", "Â°"}:
        return "deg"
    return re.sub(r"[^a-z0-9/]", "", raw)


def _register(kind: str, canonical: str, factor: float, *units: str) -> None:
    for unit in units:
        _UNIT_DEFINITIONS[_unit_key(unit)] = (kind, canonical, factor)

_register("length", "mm", 1, "mm", "millimeter", "millimeters", "millimetre", "millimetres")
_register("length", "mm", 10, "cm", "centimeter", "centimeters", "centimetre", "centimetres")
_register("length", "mm", 1000, "m", "meter", "meters", "metre", "metres")
_register("length", "mm", 25.4, "in", "inch", "inches")
_register("range", "km", 1, "km", "kilometer", "kilometers", "kilometre", "kilometres")
_register("range", "km", 1.609344, "mi", "mile", "miles")
_register("angle", "deg", 1, "deg", "degree", "degrees", "°")
_register("angle", "deg", 180 / math.pi, "rad", "radian", "radians")
_register("torque", "N·m", 1, "nm", "n·m", "n.m", "n*m")
_register("torque", "N·m", 0.001, "nmm", "n·mm", "n.mm", "n*mm")
_register("rotational_speed", "rpm", 1, "rpm", "rev/min", "revolutions/minute")
_register("rotational_speed", "rpm", 60 / (2 * math.pi), "rad/s", "radian/s", "radians/s")
_register("ratio", "ratio", 1, "ratio", "x")
_register("count", "teeth", 1, "teeth", "tooth")
_register("count", "persons", 1, "person", "persons", "seats", "seat")


class QuantityUnitError(ValueError):
    """The unit is unsupported or has the wrong physical dimension."""


class EngineeringQuantity(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: Literal["1.0"] = QUANTITY_SCHEMA_VERSION
    quantity_kind: QuantityKind
    value: float
    canonical_unit: str
    source: QuantitySource
    input_value: float | None = None
    input_unit: str | None = None
    conversion_factor: float | None = None
    unit_inferred: bool = False
    evidence: str | None = None
    source_span: dict[str, int | str] | None = None
    derivation: str | None = None
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def valid_contract(self):
        expected = {"length": "mm", "range": "km", "angle": "deg", "torque": "N·m",
                    "rotational_speed": "rpm", "ratio": "ratio", "count": None}[self.quantity_kind]
        if expected is not None and self.canonical_unit != expected:
            raise ValueError(f"{self.quantity_kind} quantities must use canonical unit {expected}.")
        if self.minimum is not None and self.value < self.minimum:
            raise ValueError("Quantity is below its permitted minimum.")
        if self.maximum is not None and self.value > self.maximum:
            raise ValueError("Quantity exceeds its permitted maximum.")
        if self.source == "derived" and not self.derivation:
            raise ValueError("Derived quantities require a derivation.")
        if self.source == "user-provided" and self.evidence is None and self.input_value is not None:
            raise ValueError("User-provided parsed quantities require source evidence.")
        if self.source_span is not None:
            start, end = self.source_span.get("start"), self.source_span.get("end")
            if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end < start:
                raise ValueError("Quantity source span indices are invalid.")
            if self.evidence is None or self.source_span.get("text") != self.evidence or end - start != len(self.evidence):
                raise ValueError("Quantity source span must identify its exact evidence text.")
        if self.input_value is not None and (self.input_unit is None or self.conversion_factor is None):
            raise ValueError("Input quantity value requires its unit and conversion factor.")
        return self


def convert_quantity(value: float, unit: str, quantity_kind: QuantityKind) -> tuple[float, str, float]:
    """Convert an explicit unit to the kind's canonical unit; never infer dimension."""
    if isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValueError("Quantity value must be a finite number.")
    normalized_unit = _unit_key(unit)
    definition = _UNIT_DEFINITIONS.get(normalized_unit)
    if definition is None:
        raise QuantityUnitError(f"Unsupported unit {unit!r}.")
    found_kind, canonical_unit, factor = definition
    if found_kind != quantity_kind:
        raise QuantityUnitError(f"Unit {unit!r} has dimension {found_kind}, not {quantity_kind}.")
    return float(value) * factor, canonical_unit, factor


_EVIDENCE_VALUE_UNIT = re.compile(
    r"(?<![\w.])([+-]?\d+(?:\.\d+)?)\s*(N\s*[Â·.*]*\s*mm|N\s*[Â·.*]*\s*m|rad(?:ians?)?/s|rev/min|rpm|degrees?|deg|°|radians?|rad|millimet(?:er|re)s?|centimet(?:er|re)s?|met(?:er|re)s?|mm|cm|m|in(?:ches?)?|km|miles?|teeth|tooth|persons?|seats?)\b",
    re.IGNORECASE,
)


def quantity_from_canonical(
    value: float,
    canonical_unit: str,
    quantity_kind: QuantityKind,
    source: QuantitySource,
    *,
    evidence: str | None = None,
    source_span: dict[str, int | str] | None = None,
    derivation: str | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
) -> EngineeringQuantity:
    """Build a versioned value from existing canonical fields and prompt provenance."""
    canonical_map = {
        "length": "mm", "range": "km", "angle": "deg", "torque": "N·m",
        "rotational_speed": "rpm", "ratio": "ratio", "count": canonical_unit,
    }
    expected_unit = canonical_map[quantity_kind]
    if canonical_unit.lower() != expected_unit.lower() and canonical_unit not in {"N·m"}:
        raise QuantityUnitError(f"Expected canonical {expected_unit} for {quantity_kind}, received {canonical_unit}.")
    original_value = None
    original_unit = None
    factor = None
    inferred = False
    if evidence:
        match = _EVIDENCE_VALUE_UNIT.search(evidence)
        if quantity_kind == "ratio":
            ratio_match = re.search(r"ratio\s*(?:of|is|=|:)?\s*(\d+(?:\.\d+)?)\s*(?::\s*1)?", evidence, re.IGNORECASE)
            if ratio_match:
                original_value, original_unit = float(ratio_match.group(1)), "ratio"
                factor = 1.0
                if not math.isclose(original_value, float(value), rel_tol=1e-8, abs_tol=1e-8):
                    raise ValueError("Canonical ratio does not match its source evidence.")
                match = None
        if match:
            original_value = float(match.group(1))
            original_unit = match.group(2).replace(" ", "")
            converted, converted_unit, factor = convert_quantity(original_value, original_unit, quantity_kind)
            if converted_unit.lower() != canonical_unit.lower() or not math.isclose(converted, float(value), rel_tol=1e-8, abs_tol=1e-8):
                raise ValueError("Canonical quantity does not match its source evidence and conversion.")
        elif source == "user-provided":
            # Some established grammar (for example, a bare pressure angle)
            # interprets the value in the field's documented canonical unit.
            original_value = float(value)
            original_unit = canonical_unit
            factor = 1.0
            inferred = True
    return EngineeringQuantity(
        quantity_kind=quantity_kind, value=float(value), canonical_unit=canonical_unit,
        source=source, input_value=original_value, input_unit=original_unit,
        conversion_factor=factor, unit_inferred=inferred, evidence=evidence,
        source_span=source_span, derivation=derivation, minimum=minimum, maximum=maximum,
    )

