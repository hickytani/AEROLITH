from __future__ import annotations

import math
from pathlib import Path

import cadquery as cq

from .domain import Design
from .engineering import bore_diameter_mm


GENERATOR_VERSION = "cq-polygon-approx-0.1"


def gear_solid(teeth: int, module: float, width: float, bore_diameter: float) -> cq.Workplane:
    """Build a valid OCCT solid using a documented polygonal tooth approximation."""
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


def build_assembly(design: Design) -> cq.Assembly:
    req = design.requirements
    p, g = design.components
    module, width = req.module_mm, req.face_width_mm
    d1, d2 = module * p.teeth, module * g.teeth
    center = (d1 + d2) / 2
    bore = bore_diameter_mm(design)
    pinion = gear_solid(p.teeth, module, width, bore)
    gear = gear_solid(g.teeth, module, width, bore)
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
    solid = gear_solid(component.teeth, req.module_mm, req.face_width_mm, bore_diameter_mm(design))
    if component_id == "gear":
        center = req.module_mm * (design.components[0].teeth + component.teeth) / 2
        solid = solid.rotate((0, 0, 0), (0, 0, 1), 180 / component.teeth).translate((center, 0, 0))
    solid.val().exportStl(
        str(target), tolerance=0.08, angularTolerance=0.15, ascii=False, relative=True, parallel=False
    )
