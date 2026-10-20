"""Rule-based conceptual EV intake and subsystem outline.

This module does not generate vehicle geometry or design values. It identifies
explicitly stated prompt requirements and returns a transparent, conceptual
system outline for a narrow electric road-vehicle request.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict


class VehicleParameter(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str
    meaning: str
    value: int | float | str | None
    unit: str
    source: Literal["user-provided", "missing"]
    evidence: str | None
    status: Literal["PROPOSED", "MISSING", "INVALID"]


class VehicleArchitectureNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    kind: Literal["assembly", "subsystem", "component"]
    parent_id: str | None
    role: str
    parameter_refs: list[str]
    status: Literal["CONCEPTUAL_ONLY"] = "CONCEPTUAL_ONLY"
    generator_available: Literal[False] = False


class VehicleRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    source_id: str
    target_id: str
    relationship: str
    status: Literal["CONCEPTUAL_ONLY"] = "CONCEPTUAL_ONLY"


class VehicleConcept(BaseModel):
    model_config = ConfigDict(extra="forbid")
    system_name: str
    parameters: list[VehicleParameter]
    nodes: list[VehicleArchitectureNode]
    relationships: list[VehicleRelationship]
    unresolved_questions: list[str]
    validation_issues: list[str]
    limitations: list[str]
    assumptions: list[str]


def _capture(patterns: list[str], text: str) -> tuple[str | None, str | None]:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1), match.group(0)
    return None, None


def _distance(text: str, dimension: str) -> tuple[float | None, str | None]:
    descriptor = "long|in length" if dimension == "length" else "wide|in width"
    distance_unit = r"mm|cm|m|millimet(?:er|re)s?|centimet(?:er|re)s?|met(?:er|re)s?"
    patterns = [
        rf"\b{dimension}\s*(?:of|is|=|:)?\s*(\d+(?:\.\d+)?)\s*({distance_unit})\b",
        rf"\b(\d+(?:\.\d+)?)\s*({distance_unit})\s+{dimension}\b",
        rf"\b(\d+(?:\.\d+)?)\s*({distance_unit})\s+(?:{descriptor})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        if pattern.startswith(rf"\b{dimension}"):
            number, unit = match.group(1), match.group(2)
        else:
            number, unit = match.group(1), match.group(2)
        normalized_unit = unit.lower()
        scale = 1 if normalized_unit in {"mm", "millimeter", "millimeters", "millimetre", "millimetres"} else 10 if normalized_unit in {"cm", "centimeter", "centimeters", "centimetre", "centimetres"} else 1000
        return float(number) * scale, match.group(0)
    return None, None


def _requirements(text: str) -> list[VehicleParameter]:
    parameters: list[VehicleParameter] = []
    occupants_raw, occupants_evidence = _capture([
        r"\b(two|three|four|five|six|\d+)\s*[- ]?seater\b",
        r"\b(two|three|four|five|six|\d+)\s+(?:occupants|seats)\b",
    ], text)
    occupant_number = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
    occupants = occupant_number.get((occupants_raw or "").lower())
    if occupants is None and occupants_raw and occupants_raw.isdigit():
        occupants = int(occupants_raw)
    parameters.append(VehicleParameter(
        name="occupant_capacity", meaning="Seating capacity", value=occupants, unit="persons",
        source="user-provided" if occupants is not None else "missing", evidence=occupants_evidence,
        status="PROPOSED" if occupants is not None else "MISSING",
    ))

    for name, meaning, unit_name in [
        ("overall_length_mm", "Overall length", "length"),
        ("overall_width_mm", "Overall width", "width"),
    ]:
        value, evidence = _distance(text, unit_name)
        parameters.append(VehicleParameter(
            name=name, meaning=meaning, value=value, unit="mm",
            source="user-provided" if value is not None else "missing", evidence=evidence,
            status="PROPOSED" if value is not None else "MISSING",
        ))

    range_raw, range_evidence = _capture([
        r"\b(?:target\s+)?range\s*(?:of|is|=|:)?\s*(\d+(?:\.\d+)?)\s*(?:km|kilomet(?:er|re)s?)\b",
        r"\b(\d+(?:\.\d+)?)\s*(?:km|kilomet(?:er|re)s?)\s+(?:target\s+)?range\b",
    ], text)
    range_value = float(range_raw) if range_raw is not None else None
    parameters.append(VehicleParameter(
        name="target_range_km", meaning="Target driving range", value=range_value, unit="km",
        source="user-provided" if range_value is not None else "missing", evidence=range_evidence,
        status="PROPOSED" if range_value is not None else "MISSING",
    ))
    propulsion = "electric" if re.search(r"\b(electric|ev|battery[ -]electric)\b", text, re.IGNORECASE) else None
    parameters.append(VehicleParameter(
        name="propulsion_type", meaning="Propulsion type", value=propulsion, unit="",
        source="user-provided" if propulsion else "missing",
        evidence=(re.search(r"\b(electric|ev|battery[ -]electric)\b", text, re.IGNORECASE).group(0)
                  if propulsion else None),
        status="PROPOSED" if propulsion else "MISSING",
    ))
    validation_issues: list[str] = []
    bounds = {
        "occupant_capacity": (1, 12),
        "overall_length_mm": (1500, 15000),
        "overall_width_mm": (800, 5000),
        "target_range_km": (1, 5000),
    }
    for parameter in parameters:
        if parameter.value is not None and isinstance(parameter.value, (int, float)) and parameter.name in bounds:
            minimum, maximum = bounds[parameter.name]
            if not minimum <= parameter.value <= maximum:
                parameter.status = "INVALID"
                validation_issues.append(
                    f"{parameter.name}={parameter.value:g} {parameter.unit} is outside the intake range {minimum} to {maximum} {parameter.unit}."
                )
    return parameters, validation_issues


def propose_electric_vehicle(text: str) -> VehicleConcept:
    parameters, validation_issues = _requirements(text)
    prompt = text.lower()
    sport = bool(re.search(r"\b(sports? car|sportscar)\b", prompt))
    seats = next((p.value for p in parameters if p.name == "occupant_capacity"), None)
    system_name = f"{seats}-seat electric {'sports car' if sport else 'vehicle'}" if seats else f"Electric {'sports car' if sport else 'vehicle'} concept"

    # Domain planner output is explicitly conceptual. There are no CAD or
    # calculation generators for these nodes in the current repository.
    groups = [
        ("structure", "Vehicle structure", "Primary load-carrying and exterior structure", ["overall_length_mm", "overall_width_mm"], [
            ("chassis-frame", "Chassis frame", "Carries occupant, suspension, and propulsion attachment loads"),
            ("body-shell", "Body shell", "Enclosure and exterior panels; structural contribution unspecified"),
        ]),
        ("running-gear", "Running gear", "Vehicle contact, steering, suspension, and braking systems", [], [
            ("front-suspension", "Front suspension", "Supports and locates the front wheels"),
            ("rear-suspension", "Rear suspension", "Supports and locates the rear wheels"),
            ("steering-system", "Steering system", "Controls front-wheel direction"),
            ("wheel-tire-assemblies", "Wheel and tire assemblies", "Road contact at four wheel locations"),
            ("braking-system", "Braking system", "Service and parking braking; sizing not determined"),
        ]),
        ("electric-propulsion", "Electric propulsion", "Stores, converts, and delivers traction energy", ["target_range_km"], [
            ("traction-battery", "Traction battery pack", "Stores high-voltage electrical energy; capacity not calculated"),
            ("battery-management", "Battery management system", "Monitors and manages the battery pack"),
            ("traction-inverter", "Traction inverter", "Controls electrical power delivered to the motor"),
            ("traction-motor", "Traction motor", "Converts electrical power to wheel-driving torque"),
            ("reduction-drive", "Reduction drive and differential", "Reduces motor speed and distributes axle torque"),
            ("half-shafts", "Half-shafts", "Transfer axle torque to driven wheels"),
        ]),
        ("vehicle-support", "Vehicle support systems", "Thermal, low-voltage, and supervisory functions", [], [
            ("thermal-management", "Thermal management", "Controls battery, inverter, and motor temperatures"),
            ("low-voltage-electrical", "Low-voltage electrical system", "Supplies control electronics and vehicle auxiliaries"),
            ("vehicle-control-unit", "Vehicle control unit", "Coordinates propulsion and vehicle state"),
            ("occupant-restraints", "Occupant restraints", "Seat belts and related occupant-restraint provisions; design not specified"),
        ]),
    ]
    if sport:
        groups.append(("performance-controls", "Performance controls", "Additional conceptual functions implied by the sports-car request", [], [
            ("drive-mode-controls", "Drive-mode controls", "Driver-selectable propulsion response; calibration unspecified"),
        ]))

    nodes: list[VehicleArchitectureNode] = []
    nodes.append(VehicleArchitectureNode(
        id="electric-vehicle", name=system_name, kind="assembly", parent_id=None,
        role="Conceptual top-level vehicle system",
        parameter_refs=[parameter.name for parameter in parameters if parameter.value is not None],
    ))
    for subsystem_id, subsystem_name, role, refs, children in groups:
        nodes.append(VehicleArchitectureNode(
            id=subsystem_id, name=subsystem_name, kind="subsystem", parent_id="electric-vehicle",
            role=role, parameter_refs=refs,
        ))
        for node_id, name, node_role in children:
            nodes.append(VehicleArchitectureNode(
                id=node_id, name=name, kind="component", parent_id=subsystem_id,
                role=node_role, parameter_refs=refs,
            ))

    relationships = [
        VehicleRelationship(id="battery-to-inverter", source_id="traction-battery", target_id="traction-inverter", relationship="high_voltage_dc_power"),
        VehicleRelationship(id="inverter-to-motor", source_id="traction-inverter", target_id="traction-motor", relationship="controlled_electrical_power"),
        VehicleRelationship(id="motor-to-reduction", source_id="traction-motor", target_id="reduction-drive", relationship="mechanical_torque"),
        VehicleRelationship(id="reduction-to-shafts", source_id="reduction-drive", target_id="half-shafts", relationship="driveline_torque"),
        VehicleRelationship(id="shafts-to-wheels", source_id="half-shafts", target_id="wheel-tire-assemblies", relationship="wheel_torque"),
        VehicleRelationship(id="steering-to-wheels", source_id="steering-system", target_id="wheel-tire-assemblies", relationship="steering_interface"),
        VehicleRelationship(id="brakes-to-wheels", source_id="braking-system", target_id="wheel-tire-assemblies", relationship="braking_interface"),
        VehicleRelationship(id="structure-to-running-gear", source_id="chassis-frame", target_id="front-suspension", relationship="structural_mounting_interface"),
        VehicleRelationship(id="structure-to-propulsion", source_id="chassis-frame", target_id="traction-battery", relationship="structural_mounting_interface"),
    ]
    unresolved = [
        f"Provide {parameter.meaning.lower()}" for parameter in parameters if parameter.value is None
    ]
    unresolved.extend(f"Review {issue}" for issue in validation_issues)
    unresolved.extend([
        "Define wheelbase, track widths, ground clearance, and driven axle.",
        "Define curb-mass target, payload, maximum speed, acceleration, and gradeability.",
        "Define the range drive cycle, ambient conditions, usable battery reserve, charging target, and energy-consumption basis.",
        "Select battery chemistry, cell architecture, motor topology, voltage, and thermal limits before sizing components.",
        "Define applicable road-vehicle safety and regulatory requirements before detailed design.",
    ])
    limitations = [
        "This rule-based output is a conceptual subsystem outline, not a complete vehicle design or validated component selection.",
        "No vehicle CAD geometry, 2D drawings, BOM quantities, battery sizing, mass estimate, performance calculation, or safety analysis is generated.",
        "Every listed subsystem and interface is conceptual; no geometry generator or vehicle engineering family is registered.",
        "No LLM or external provider was called. Prompt matching uses deterministic local patterns.",
    ]
    return VehicleConcept(
        system_name=system_name,
        parameters=parameters,
        nodes=nodes,
        relationships=relationships,
        unresolved_questions=unresolved,
        validation_issues=validation_issues,
        limitations=limitations,
        assumptions=[
            "Only the stated seat count, overall dimensions, range target, and electric propulsion intent are treated as user requirements.",
            "The subsystem outline is a deterministic conceptual starting point; components are not selected or sized.",
        ],
    )
