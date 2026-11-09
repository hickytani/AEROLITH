from __future__ import annotations

import math

from pint import UnitRegistry

from .domain import Design

import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

CALCULATION_METHOD_VERSION = "spur-gear-involute-dimensions-0.3"

units = UnitRegistry()


def lewis_form_factor(teeth: int, pressure_angle_deg: float = 20.0) -> float:
    """Lewis form factor Y (metric, based on module) for standard full-depth involute teeth.

    Standard tabular values for 20 deg full-depth involute teeth with linear interpolation.
    Scaled for non-standard pressure angles via the standard tan(alpha) / tan(20 deg) ratio.
    """
    table = [
        (12, 0.245), (13, 0.261), (14, 0.277), (15, 0.290), (16, 0.296),
        (17, 0.303), (18, 0.309), (19, 0.314), (20, 0.322), (22, 0.331),
        (24, 0.338), (26, 0.346), (28, 0.353), (30, 0.359), (34, 0.371),
        (38, 0.384), (43, 0.397), (50, 0.409), (60, 0.422), (75, 0.435),
        (100, 0.447), (120, 0.459), (150, 0.468), (300, 0.478),
    ]
    if teeth <= table[0][0]:
        base_y = table[0][1]
    elif teeth >= table[-1][0]:
        base_y = table[-1][1]
    else:
        for i in range(len(table) - 1):
            z1, y1 = table[i]
            z2, y2 = table[i + 1]
            if z1 <= teeth <= z2:
                base_y = y1 + (y2 - y1) * (teeth - z1) / (z2 - z1)
                break
        else:
            base_y = 0.320
    pa_factor = math.tan(math.radians(pressure_angle_deg)) / math.tan(math.radians(20.0))
    return round(base_y * pa_factor, 4)


def lewis_bending_stress(tangential_load_N: float, face_width_mm: float, module_mm: float, lewis_y: float) -> float:
    """Lewis bending stress at tooth root in MPa (N/mm^2).

    sigma = F_t / (b * m * Y)
    Assumes nominal static load, single-tooth contact at the tip, and zero dynamic factor.
    """
    if face_width_mm <= 0 or module_mm <= 0 or lewis_y <= 0:
        return 0.0
    return tangential_load_N / (face_width_mm * module_mm * lewis_y)


def bore_diameter_mm(design: Design) -> float:
    req = design.requirements
    if req.bore_diameter_mm is not None:
        return req.bore_diameter_mm
    minimum_teeth = min(component.teeth for component in design.components)
    return min(max(req.module_mm * 2, 4.0), req.module_mm * (minimum_teeth - 2.5) * 0.7)


def derive(design: Design) -> dict:
    req = design.requirements
    pinion, gear = design.components
    module = req.module_mm * units.mm
    d1 = module * pinion.teeth
    d2 = module * gear.teeth
    d1_val = d1.to(units.mm).magnitude
    d2_val = d2.to(units.mm).magnitude
    pressure = math.radians(req.pressure_angle_deg)
    ratio = gear.teeth / pinion.teeth

    # Tangential tooth load at operating pitch circle (N): F_t = 2000 * T1 / d1
    tangential_load_N = (2000.0 * req.input_torque_Nm) / d1_val if d1_val > 0 else 0.0
    y1 = lewis_form_factor(pinion.teeth, req.pressure_angle_deg)
    y2 = lewis_form_factor(gear.teeth, req.pressure_angle_deg)
    sigma_b1 = lewis_bending_stress(tangential_load_N, req.face_width_mm, req.module_mm, y1)
    sigma_b2 = lewis_bending_stress(tangential_load_N, req.face_width_mm, req.module_mm, y2)

    result = {
        "gear_ratio": ratio,
        "center_distance_mm": ((d1 + d2) / 2).to(units.mm).magnitude,
        "pinion_pitch_diameter_mm": d1_val,
        "gear_pitch_diameter_mm": d2_val,
        "pinion_base_diameter_mm": req.module_mm * pinion.teeth * math.cos(pressure),
        "gear_base_diameter_mm": req.module_mm * gear.teeth * math.cos(pressure),
        "pressure_angle_deg": req.pressure_angle_deg,
        "pinion_outer_diameter_mm": req.module_mm * (pinion.teeth + 2),
        "gear_outer_diameter_mm": req.module_mm * (gear.teeth + 2),
        "output_speed_rpm": req.input_speed_rpm / ratio,
        "ideal_output_torque_Nm": req.input_torque_Nm * ratio,
        "bore_diameter_mm": bore_diameter_mm(design),
        "tangential_load_N": tangential_load_N,
        "pinion_lewis_form_factor": y1,
        "gear_lewis_form_factor": y2,
        "pinion_bending_stress_MPa": sigma_b1,
        "gear_bending_stress_MPa": sigma_b2,
        "contact_stress_note": (
            "Hertzian contact stress requires material elasticity (Young's modulus E, "
            "Poisson's ratio \u03bd) which are not specified in the project requirements."
        ),
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
                "lewis_form_factor": y1 if component.id == "pinion" else y2,
                "bending_stress_MPa": sigma_b1 if component.id == "pinion" else sigma_b2,
            }
            for component in (pinion, gear)
        ],
    }
    # Expose hub geometry when hub extension parameters are committed
    if req.hub_diameter_mm is not None and req.hub_length_mm is not None:
        hub_r = req.hub_diameter_mm / 2
        result["hub_geometry"] = {
            "hub_diameter_mm": req.hub_diameter_mm,
            "hub_length_mm": req.hub_length_mm,
            "bore_diameter_mm": bore_diameter_mm(design),
            "hub_volume_mm3": round(math.pi * hub_r ** 2 * req.hub_length_mm, 3),
            "note": (
                "Cylindrical shaft hub extension; outside diameter must exceed bore for valid OCCT solid. "
                "Hub geometry is an envelope approximation only — no spline, interference-fit, "
                "fatigue, or strength analysis is performed."
            ),
        }
    if req.keyway_width_mm is not None and req.keyway_depth_mm is not None:
        result["keyway_geometry"] = {
            "keyway_width_mm": req.keyway_width_mm,
            "keyway_depth_mm": req.keyway_depth_mm,
            "bore_diameter_mm": bore_diameter_mm(design),
            "standard": "DIN 6885 / ISO 773 parallel drive keyway",
            "note": "Parallel keyway slot cut into shaft bore for positive torque transmission.",
        }
    return result



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
        ("tangential_load_N", "Tangential load at pitch circle", "N", "2000 · T₁ / d₁", f"2000 × {req.input_torque_Nm:g} N·m / {d['pinion_pitch_diameter_mm']:g} mm", ["Nominal tangential tooth force at operating pitch diameter; dynamic and overload factors are excluded."]),
        ("pinion_bending_stress_MPa", "Pinion Lewis bending stress", "MPa", "F_t / (b · m · Y₁)", f"{d['tangential_load_N']:.2f} N / ({req.face_width_mm:g} mm × {req.module_mm:g} mm × {d['pinion_lewis_form_factor']:.4f})", ["Lewis bending equation at tooth root. Assumes full load carried by a single tooth tip, static loading (K_v=1.0), no stress concentration factor. Material allowable stress is not specified."]),
        ("gear_bending_stress_MPa", "Driven gear Lewis bending stress", "MPa", "F_t / (b · m · Y₂)", f"{d['tangential_load_N']:.2f} N / ({req.face_width_mm:g} mm × {req.module_mm:g} mm × {d['gear_lewis_form_factor']:.4f})", ["Lewis bending equation at tooth root. Assumes full load carried by a single tooth tip, static loading (K_v=1.0), no stress concentration factor. Material allowable stress is not specified."]),
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
