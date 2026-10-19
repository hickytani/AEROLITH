import math

import cadquery as cq
from OCP.StlAPI import StlAPI_Reader
from OCP.TopoDS import TopoDS_Shape
import pytest

from aeropkmech.cad import build_assembly, export_step, export_stl, gear_solid
from aeropkmech.store import default_design


def assert_kernel_gear(shape, teeth, module, width, bore_diameter):
    assert shape.isValid()
    assert len(shape.Solids()) == 1
    volume = shape.Volume()
    assert math.isfinite(volume) and volume > 0
    bounds = shape.BoundingBox()
    assert bounds.zlen == pytest.approx(width, abs=1e-7)

    # The unique non-bore vertices are the actual four-per-tooth polygon boundary.
    points = {(round(vertex.X, 8), round(vertex.Y, 8)) for vertex in shape.Vertices()}
    radii = [math.hypot(x, y) for x, y in points if math.hypot(x, y) > bore_diameter / 2 + 1e-6]
    root_radius = module * (teeth - 2.5) / 2
    tip_radius = module * (teeth + 2) / 2
    assert len(radii) == 4 * teeth
    roots = [radius for radius in radii if math.isclose(radius, root_radius, rel_tol=0, abs_tol=1e-7)]
    tips = [radius for radius in radii if math.isclose(radius, tip_radius, rel_tol=0, abs_tol=1e-7)]
    assert len(roots) == 2 * teeth
    assert len(tips) == 2 * teeth

    # Through-bore is represented by one circular edge on each end face.
    bore_edges = [edge.radius() for edge in shape.Edges() if edge.geomType() == "CIRCLE"]
    assert len(bore_edges) == 2
    assert all(radius == pytest.approx(bore_diameter / 2, abs=1e-7) for radius in bore_edges)


def test_minimum_supported_dimensions_keep_cad_solids_valid():
    design = default_design()
    design.components[0].teeth = 8
    design.components[1].teeth = 8
    design.requirements.gear_ratio = 1
    design.requirements.module_mm = 0.5
    design.requirements.face_width_mm = 2
    assembly = build_assembly(design)
    assert len(assembly.children) == 2
    for component, teeth in zip(assembly.children, (8, 8)):
        assert_kernel_gear(component.obj.val(), teeth, 0.5, 2, 1.925)


def test_maximum_supported_dimensions_keep_cad_solids_valid():
    design = default_design()
    design.components[0].teeth = 80
    design.components[1].teeth = 120
    design.requirements.gear_ratio = 1.5
    design.requirements.module_mm = 6
    design.requirements.face_width_mm = 60
    assembly = build_assembly(design)
    assert len(assembly.children) == 2
    for component, teeth in zip(assembly.children, (80, 120)):
        assert_kernel_gear(component.obj.val(), teeth, 6, 60, 12)


def test_default_polygon_vertices_bore_and_analytical_xy_envelope():
    # Static radii and envelope are independently calculated from the documented
    # vertex schedule; tolerances absorb floating-point trig and OCCT boolean noise.
    shape = gear_solid(teeth=18, module=2, width=12, bore_diameter=4).val()
    assert_kernel_gear(shape, teeth=18, module=2, width=12, bore_diameter=4)
    bounds = shape.BoundingBox()
    expected_half_span = 20 * math.cos(math.radians(5))
    assert bounds.xlen == pytest.approx(2 * expected_half_span, abs=1e-7)
    assert bounds.ylen == pytest.approx(2 * expected_half_span, abs=1e-7)
    # The reference addendum diameter is 40 mm; this polygon's measured X/Y
    # spans are smaller because its maximum-radius vertices are not on the axes.
    assert 2 * expected_half_span < 40


def test_step_and_stl_exports_reopen_in_opencascade(tmp_path):
    design = default_design()
    step_path = tmp_path / "roundtrip.step"
    stl_path = tmp_path / "roundtrip.stl"
    export_step(design, step_path)
    export_stl(design, stl_path)

    imported_step = cq.importers.importStep(str(step_path)).val()
    assert imported_step.isValid()
    assert len(imported_step.Solids()) == 2
    expected_volume = sum(component.obj.val().Volume() for component in build_assembly(design).children)
    assert math.isfinite(imported_step.Volume())
    assert imported_step.Volume() == pytest.approx(expected_volume, rel=1e-8, abs=1e-7)

    imported_mesh = TopoDS_Shape()
    assert StlAPI_Reader().Read(imported_mesh, str(stl_path))
    assert not imported_mesh.IsNull()
    mesh_shape = cq.Shape.cast(imported_mesh)
    assert len(mesh_shape.Faces()) > 0
    step_bounds, mesh_bounds = imported_step.BoundingBox(), mesh_shape.BoundingBox()
    assert mesh_bounds.zlen == pytest.approx(12, abs=1e-7)
    # STL tessellation uses CadQuery's 0.08 mm linear tolerance; allow 0.2 mm
    # on imported assembly bounds for tessellation and kernel representation.
    assert mesh_bounds.xlen == pytest.approx(step_bounds.xlen, abs=0.2)
    assert mesh_bounds.ylen == pytest.approx(step_bounds.ylen, abs=0.2)
