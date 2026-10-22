from __future__ import annotations

import math
from pathlib import Path

import cadquery as cq

from .domain import Design
from .engineering import bore_diameter_mm


GENERATOR_VERSION = "cq-involute-spline-profile-0.3"
LEGACY_GENERATOR_VERSION = "cq-polygon-approx-0.1"
# The profile is interpolated with one OCCT spline edge per flank, through these
# exact involute samples. Arc and root-connector edges remain separate.
INVOLUTE_FLANK_STEPS = 16
ROOT_ARC_STEPS = 3
TIP_ARC_STEPS = 4


def legacy_polygon_gear_solid(teeth: int, module: float, width: float, bore_diameter: float) -> cq.Workplane:
    """Reproduce the historical polygon generator for regression/reference use only."""
    pitch = 2 * math.pi / teeth
    root_radius = module * (teeth - 2.5) / 2
    tip_radius = module * (teeth + 2) / 2
    outline: list[tuple[float, float]] = []
    for i in range(teeth):
        angle = i * pitch
        for theta, radius in (
            (angle - pitch * 0.35, root_radius),
            (angle - pitch * 0.25, tip_radius),
            (angle + pitch * 0.25, tip_radius),
            (angle + pitch * 0.35, root_radius),
        ):
            outline.append((radius * math.cos(theta), radius * math.sin(theta)))
    solid = cq.Workplane("XY").polyline(outline).close().extrude(width / 2, both=True)
    if bore_diameter > 0:
        solid = solid.faces(">Z").workplane().hole(bore_diameter)
    return solid


def involute_xy(base_radius: float, parameter: float) -> tuple[float, float]:
    """Point on the involute of a base circle, before tooth-angle rotation.

    ``parameter`` is tan(alpha), where alpha is the local pressure angle.
    The returned curve is exact at each sampled point. The CAD boundary
    interpolates 17 deterministic points per flank with an OCCT spline edge.
    """
    if base_radius <= 0 or parameter < 0 or not math.isfinite(parameter):
        raise ValueError("Involute base radius must be positive and its parameter finite and nonnegative.")
    x = base_radius * (math.cos(parameter) + parameter * math.sin(parameter))
    y = base_radius * (math.sin(parameter) - parameter * math.cos(parameter))
    return x, y


def _rotate(point: tuple[float, float], angle: float) -> tuple[float, float]:
    x, y = point
    cosine, sine = math.cos(angle), math.sin(angle)
    return x * cosine - y * sine, x * sine + y * cosine


def gear_profile_points(
    teeth: int, module: float, pressure_angle_deg: float = 20.0,
) -> list[tuple[float, float]]:
    """Return deterministic exact involute samples for a closed perimeter.

    Assumptions: ordinary unshifted external spur gear; addendum=m, dedendum=1.25m;
    zero nominal backlash; straight radial root connector below the active
    involute. The connector is an explicit approximation, not a cutter trochoid
    or fillet. Samples are uniform in the involute roll parameter.
    """
    if isinstance(teeth, bool) or not isinstance(teeth, int) or teeth < 8 or teeth > 120:
        raise ValueError("Gear tooth count must be an integer from 8 through 120.")
    if not math.isfinite(module) or not 0.5 <= module <= 6:
        raise ValueError("Gear module must be finite and between 0.5 and 6 mm.")
    if not math.isfinite(pressure_angle_deg) or not 14 <= pressure_angle_deg <= 30:
        raise ValueError("Pressure angle must be between 14 and 30 degrees.")

    pitch_radius = module * teeth / 2
    base_radius = pitch_radius * math.cos(math.radians(pressure_angle_deg))
    root_radius = module * (teeth - 2.5) / 2
    tip_radius = module * (teeth + 2) / 2
    flank_start_radius = max(base_radius, root_radius)
    if tip_radius <= flank_start_radius:
        raise ValueError("Addendum radius must exceed the base/root radius for an involute flank.")

    pressure = math.radians(pressure_angle_deg)
    start_t = math.sqrt(max(0.0, (flank_start_radius / base_radius) ** 2 - 1))
    tip_t = math.sqrt((tip_radius / base_radius) ** 2 - 1)
    involute_at_pressure = math.tan(pressure) - pressure
    pitch_angle = 2 * math.pi / teeth
    half_tooth_at_t = lambda t: math.pi / (2 * teeth) + (t - math.atan(t)) - involute_at_pressure
    half_start = half_tooth_at_t(start_t)

    points: list[tuple[float, float]] = []

    def append(point: tuple[float, float]) -> None:
        if not points or math.dist(point, points[-1]) > 1e-10:
            points.append(point)

    def polar(radius: float, angle: float) -> tuple[float, float]:
        return radius * math.cos(angle), radius * math.sin(angle)

    # The left/right involutes are mirrors around each tooth center. Generate
    # one pitch sector at a time and join neighboring teeth with root-circle arcs.
    for tooth_index in range(teeth):
        center = tooth_index * pitch_angle
        previous_right = center - pitch_angle + half_start
        current_left = center - half_start
        for step in range(ROOT_ARC_STEPS + 1):
            angle = previous_right + (current_left - previous_right) * step / ROOT_ARC_STEPS
            append(polar(root_radius, angle))

        left_base = polar(flank_start_radius, center - half_start)
        append(left_base)
        for step in range(1, INVOLUTE_FLANK_STEPS + 1):
            parameter = start_t + (tip_t - start_t) * step / INVOLUTE_FLANK_STEPS
            # Mirror the exact right involute point across the tooth centerline.
            right_local = _rotate(involute_xy(base_radius, parameter), math.pi / (2 * teeth) - involute_at_pressure)
            left = _rotate((right_local[0], -right_local[1]), center)
            append(left)

        half_tip = half_tooth_at_t(tip_t)
        for step in range(1, TIP_ARC_STEPS + 1):
            angle = center - half_tip + (2 * half_tip) * step / TIP_ARC_STEPS
            append(polar(tip_radius, angle))

        for step in range(INVOLUTE_FLANK_STEPS - 1, -1, -1):
            parameter = start_t + (tip_t - start_t) * step / INVOLUTE_FLANK_STEPS
            right = _rotate(involute_xy(base_radius, parameter), center + math.pi / (2 * teeth) - involute_at_pressure)
            append(right)
        append(polar(root_radius, center + half_start))

    if len(points) < teeth * 2 * INVOLUTE_FLANK_STEPS:
        raise ValueError("Generated involute perimeter is incomplete.")
    return points


def gear_profile_wire(teeth: int, module: float, pressure_angle_deg: float = 20.0) -> cq.Wire:
    """Build a closed wire with one interpolated spline edge per involute flank."""
    # Validate and share the same assumptions/parameter bounds as the point API.
    gear_profile_points(teeth, module, pressure_angle_deg)
    pressure = math.radians(pressure_angle_deg)
    pitch_radius = module * teeth / 2
    base_radius = pitch_radius * math.cos(pressure)
    root_radius = module * (teeth - 2.5) / 2
    tip_radius = module * (teeth + 2) / 2
    start_radius = max(base_radius, root_radius)
    start_t = math.sqrt(max(0.0, (start_radius / base_radius) ** 2 - 1))
    tip_t = math.sqrt((tip_radius / base_radius) ** 2 - 1)
    inv_pressure = math.tan(pressure) - pressure
    pitch_angle = 2 * math.pi / teeth
    halfpitch = math.pi / (2 * teeth)
    half_start = halfpitch + start_t - math.atan(start_t) - inv_pressure
    half_tip = halfpitch + tip_t - math.atan(tip_t) - inv_pressure
    edges: list[cq.Edge] = []

    def polar(radius: float, angle: float) -> tuple[float, float]:
        return radius * math.cos(angle), radius * math.sin(angle)

    def spline(points: list[tuple[float, float]]) -> cq.Edge:
        return cq.Edge.makeSpline([cq.Vector(x, y, 0) for x, y in points], tol=1e-8)

    def connector(first: tuple[float, float], last: tuple[float, float]) -> None:
        if math.dist(first, last) > 1e-9:
            edges.append(cq.Edge.makeLine(cq.Vector(first[0], first[1], 0), cq.Vector(last[0], last[1], 0)))

    for index in range(teeth):
        center = index * pitch_angle
        root_start_angle = center - pitch_angle + half_start
        root_end_angle = center - half_start
        root_arc = [polar(root_radius, root_start_angle + (root_end_angle - root_start_angle) * step / ROOT_ARC_STEPS) for step in range(ROOT_ARC_STEPS + 1)]
        edges.append(spline(root_arc))

        left_root = polar(root_radius, center - half_start)
        left_start = polar(start_radius, center - half_start)
        connector(left_root, left_start)
        left_flank = []
        for step in range(INVOLUTE_FLANK_STEPS + 1):
            parameter = start_t + (tip_t - start_t) * step / INVOLUTE_FLANK_STEPS
            right_local = _rotate(involute_xy(base_radius, parameter), halfpitch - inv_pressure)
            left_flank.append(_rotate((right_local[0], -right_local[1]), center))
        edges.append(spline(left_flank))

        tip_arc = [polar(tip_radius, center - half_tip + 2 * half_tip * step / TIP_ARC_STEPS) for step in range(TIP_ARC_STEPS + 1)]
        edges.append(spline(tip_arc))

        right_flank = [
            _rotate(involute_xy(base_radius, start_t + (tip_t - start_t) * step / INVOLUTE_FLANK_STEPS), center + halfpitch - inv_pressure)
            for step in range(INVOLUTE_FLANK_STEPS, -1, -1)
        ]
        edges.append(spline(right_flank))
        right_start = polar(start_radius, center + half_start)
        right_root = polar(root_radius, center + half_start)
        connector(right_start, right_root)

    wire = cq.Wire.assembleEdges(edges)
    if not wire.IsClosed():
        raise ValueError("Generated involute spline wire is not closed.")
    return wire


def gear_solid(
    teeth: int, module: float, width: float, bore_diameter: float,
    pressure_angle_deg: float = 20.0,
) -> cq.Workplane:
    """Build a real OCCT solid with spline-interpolated involute gear flanks."""
    if not math.isfinite(width) or not 2 <= width <= 60:
        raise ValueError("Gear face width must be finite and between 2 and 60 mm.")
    if not math.isfinite(bore_diameter) or bore_diameter < 0:
        raise ValueError("Gear bore diameter must be finite and nonnegative.")
    wire = gear_profile_wire(teeth, module, pressure_angle_deg)
    solid_shape = cq.Solid.extrudeLinear(wire, [], cq.Vector(0, 0, width)).translate((0, 0, -width / 2))
    solid = cq.Workplane("XY").newObject([solid_shape])
    if bore_diameter > 0:
        solid = solid.faces(">Z").workplane().hole(bore_diameter)
    if not solid.val().isValid() or not math.isfinite(solid.val().Volume()) or solid.val().Volume() <= 0:
        raise ValueError("Involute gear profile did not produce a valid positive-volume solid.")
    return solid


def build_assembly(design: Design) -> cq.Assembly:
    req = design.requirements
    p, g = design.components
    module, width = req.module_mm, req.face_width_mm
    d1, d2 = module * p.teeth, module * g.teeth
    center = (d1 + d2) / 2
    bore = bore_diameter_mm(design)
    pinion = gear_solid(p.teeth, module, width, bore, req.pressure_angle_deg)
    gear = gear_solid(g.teeth, module, width, bore, req.pressure_angle_deg)
    assembly = cq.Assembly(name=f"spur_gear_pair_r{design.revision}")
    assembly.add(pinion, name="pinion", color=cq.Color(0.0, 0.66, 0.78))
    # Align tooth and gap at the mesh line for a clearer educational assembly view.
    assembly.add(
        gear,
        name="driven_gear",
        loc=cq.Location(cq.Vector(center, 0, 0), cq.Vector(0, 0, 1), 180 / g.teeth),
        color=cq.Color(0.61, 0.68, 0.72),
    )
    return assembly


def export_stl(design: Design, target: Path) -> None:
    # Explicit serial meshing avoids OCCT worker-pool instability on constrained
    # Windows workstations while keeping the same tessellation tolerances.
    build_assembly(design).toCompound().exportStl(
        str(target), tolerance=0.08, angularTolerance=0.15, ascii=False, relative=True, parallel=False
    )


def export_step(design: Design, target: Path) -> None:
    build_assembly(design).export(str(target), exportType="STEP")


def export_component_stl(design: Design, component_id: str, target: Path) -> None:
    req = design.requirements
    component = next(item for item in design.components if item.id == component_id)
    solid = gear_solid(component.teeth, req.module_mm, req.face_width_mm, bore_diameter_mm(design), req.pressure_angle_deg)
    if component_id == "gear":
        center = req.module_mm * (design.components[0].teeth + component.teeth) / 2
        solid = solid.rotate((0, 0, 0), (0, 0, 1), 180 / component.teeth).translate((center, 0, 0))
    solid.val().exportStl(
        str(target), tolerance=0.08, angularTolerance=0.15, ascii=False, relative=True, parallel=False
    )
