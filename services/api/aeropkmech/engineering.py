from __future__ import annotations

import math

from pint import UnitRegistry

from .domain import Design

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
    ratio = gear.teeth / pinion.teeth
    return {
        "gear_ratio": ratio,
        "center_distance_mm": ((d1 + d2) / 2).to(units.mm).magnitude,
        "pinion_pitch_diameter_mm": d1.to(units.mm).magnitude,
        "gear_pitch_diameter_mm": d2.to(units.mm).magnitude,
        "pinion_outer_diameter_mm": req.module_mm * (pinion.teeth + 2),
        "gear_outer_diameter_mm": req.module_mm * (gear.teeth + 2),
        "output_speed_rpm": req.input_speed_rpm / ratio,
        "ideal_output_torque_Nm": req.input_torque_Nm * ratio,
        "bore_diameter_mm": bore_diameter_mm(design),
        "geometry_note": (
            "The reported outer/root diameters are conventional unshifted full-depth reference-circle values; "
            "the CAD boundary is a polygonal approximation with phase-dependent axis-aligned bounds, not an involute profile. "
            "Reference-circle dimensions and valid solids do not establish tooth engagement or manufacturing suitability."
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


def validate(design: Design) -> list[str]:
    issues = []
    result = derive(design)
    if result["gear_ratio"] != design.requirements.gear_ratio:
        issues.append("Stored ratio does not agree with the component tooth counts.")
    if not math.isfinite(result["center_distance_mm"]):
        issues.append("Center distance is not finite.")
    return issues
