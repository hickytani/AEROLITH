from __future__ import annotations

import math

from pint import UnitRegistry

from .domain import Design

CALCULATION_METHOD_VERSION = "spur-gear-involute-dimensions-0.2"

units = UnitRegistry()


def bore_diameter_mm(design: Design) -> float:
    req = design.requirements
    minimum_teeth = min(component.teeth for component in design.components)
    return min(max(req.module_mm * 2, 4.0), req.module_mm * (minimum_teeth - 2.5) * 0.7)


def derive(design: Design) -> dict:
    req = design.requirements
    pinion, gear = design.components
    module = req.module_mm * units.mm
    d1 = module * pinion.teeth
    d2 = module * gear.teeth
    pressure = math.radians(req.pressure_angle_deg)
    ratio = gear.teeth / pinion.teeth
    return {
        "gear_ratio": ratio,
        "center_distance_mm": ((d1 + d2) / 2).to(units.mm).magnitude,
        "pinion_pitch_diameter_mm": d1.to(units.mm).magnitude,
        "gear_pitch_diameter_mm": d2.to(units.mm).magnitude,
        "pinion_base_diameter_mm": req.module_mm * pinion.teeth * math.cos(pressure),
        "gear_base_diameter_mm": req.module_mm * gear.teeth * math.cos(pressure),
        "pressure_angle_deg": req.pressure_angle_deg,
        "pinion_outer_diameter_mm": req.module_mm * (pinion.teeth + 2),
        "gear_outer_diameter_mm": req.module_mm * (gear.teeth + 2),
        "output_speed_rpm": req.input_speed_rpm / ratio,
        "ideal_output_torque_Nm": req.input_torque_Nm * ratio,
        "bore_diameter_mm": bore_diameter_mm(design),
        "geometry_note": (
            "CAD uses a sampled mathematical involute flank for an ordinary unshifted external spur gear, with addendum m, "
            "dedendum 1.25m, zero nominal backlash, and a straight radial root connector below the base circle. "
            "The root connector is not a cutter trochoid; spline interpolation and valid solids do not establish contact, "
            "interference-free operation, standards compliance, or manufacturing suitability."
        ),
        "components": [
            {
                "id": component.id,
                "name": component.name,
                "teeth": component.teeth,
                "pitch_diameter_mm": (module * component.teeth).to(units.mm).magnitude,
                "outer_diameter_mm": req.module_mm * (component.teeth + 2),
                "root_diameter_mm": req.module_mm * (component.teeth - 2.5),
                "face_width_mm": req.face_width_mm,
                "bore_diameter_mm": bore_diameter_mm(design),
            }
            for component in (pinion, gear)
        ],
    }


def calculation_details(design: Design) -> dict:
    """Inspectable calculation values and method provenance for this revision."""
    req = design.requirements
    pinion, gear = design.components
    d = derive(design)
    common = ["Ordinary external spur pair with common module; rotation direction is not shown in speed magnitude."]
    specs = [
        ("gear_ratio", "Transmission ratio", "ratio", "z₂ / z₁", f"{gear.teeth} / {pinion.teeth}", ["External-pair speed magnitude; driven gear rotates in the opposite direction."]),
        ("pinion_pitch_diameter_mm", "Pinion pitch diameter", "mm", "m z₁", f"{req.module_mm:g} mm × {pinion.teeth}", common),
        ("gear_pitch_diameter_mm", "Driven gear pitch diameter", "mm", "m z₂", f"{req.module_mm:g} mm × {gear.teeth}", common),
        ("pinion_base_diameter_mm", "Pinion base-circle diameter", "mm", "d_b = d cos α", f"{d['pinion_pitch_diameter_mm']:g} mm × cos({req.pressure_angle_deg:g}°)", ["Ordinary unshifted involute reference geometry."]),
        ("gear_base_diameter_mm", "Driven gear base-circle diameter", "mm", "d_b = d cos α", f"{d['gear_pitch_diameter_mm']:g} mm × cos({req.pressure_angle_deg:g}°)", ["Ordinary unshifted involute reference geometry."]),
        ("center_distance_mm", "Center distance", "mm", "(d₁ + d₂) / 2", f"({d['pinion_pitch_diameter_mm']:g} mm + {d['gear_pitch_diameter_mm']:g} mm) / 2", common),
        ("output_speed_rpm", "Ideal output speed", "rpm", "n₁ / i", f"{req.input_speed_rpm:g} rpm / {d['gear_ratio']:g}", ["Ideal rigid kinematics; speed losses and compliance are excluded."]),
        ("ideal_output_torque_Nm", "Ideal output torque", "N·m", "T₁ × i", f"{req.input_torque_Nm:g} N·m × {d['gear_ratio']:g}", ["Lossless power transmission assumed; not a load rating."]),
    ]
    return {
        "provenance": {"design_revision": design.revision, "family_id": design.family, "schema_version": design.schema_version, "method_version": CALCULATION_METHOD_VERSION},
        "results": [
            {"key": key, "name": name, "value": d[key], "unit": unit, "formula": formula, "substitution": substitution, "assumptions": assumptions, "reference": "See docs/engineering-reference-validation.md; base-circle equations do not establish contact, strength, or manufacturing suitability.", "method_version": CALCULATION_METHOD_VERSION, "status": "CALCULATED", "design_revision": design.revision}
            for key, name, unit, formula, substitution, assumptions in specs
        ],
    }


def validate(design: Design) -> list[str]:
    issues = []
    result = derive(design)
    if result["gear_ratio"] != design.requirements.gear_ratio:
        issues.append("Stored ratio does not agree with the component tooth counts.")
    if not math.isfinite(result["center_distance_mm"]):
        issues.append("Center distance is not finite.")
    return issues
