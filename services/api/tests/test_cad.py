import math

import cadquery as cq
from OCP.StlAPI import StlAPI_Reader
from OCP.TopoDS import TopoDS_Shape
import pytest

from aeropkmech.cad import INVOLUTE_FLANK_STEPS, build_assembly, export_step, export_stl, gear_profile_points, gear_profile_wire, gear_solid, involute_xy
from aeropkmech.store import default_design


def assert_kernel_gear(shape, teeth, module, width, bore_diameter):
    assert shape.isValid()
    assert len(shape.Solids()) == 1
    volume = shape.Volume()
    assert math.isfinite(volume) and volume > 0
    bounds = shape.BoundingBox()
    assert bounds.zlen == pytest.approx(width, abs=5e-7)

    # Inspect the actual spline profile vertices and bore edges in OCCT.
    points = {(round(vertex.X, 8), round(vertex.Y, 8)) for vertex in shape.Vertices()}
    radii = [math.hypot(x, y) for x, y in points if math.hypot(x, y) > bore_diameter / 2 + 1e-6]
    root_radius = module * (teeth - 2.5) / 2
    tip_radius = module * (teeth + 2) / 2
    assert len(radii) >= teeth * 4
    assert min(radii) == pytest.approx(root_radius, abs=1e-7)
    assert max(radii) == pytest.approx(tip_radius, abs=1e-7)

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
    design.requirements.pressure_angle_deg = 14
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
    design.requirements.pressure_angle_deg = 30
    assembly = build_assembly(design)
    assert len(assembly.children) == 2
    for component, teeth in zip(assembly.children, (80, 120)):
        assert_kernel_gear(component.obj.val(), teeth, 6, 60, 12)


def test_default_involute_vertices_bore_and_reference_circle_envelope():
    shape = gear_solid(teeth=18, module=2, width=12, bore_diameter=4).val()
    assert_kernel_gear(shape, teeth=18, module=2, width=12, bore_diameter=4)
    bounds = shape.BoundingBox()
    assert bounds.xlen == pytest.approx(40, abs=5e-7)
    assert bounds.ylen > 39.9
    assert bounds.ylen <= 40 + 5e-7


def test_geometry_changes_when_tooth_parameters_change():
    default = default_design()
    changed = default.model_copy(deep=True)
    changed.components[0].teeth = 12
    changed.components[1].teeth = 30
    changed.requirements.gear_ratio = 2.5
    original_shape = gear_solid(18, 2, 12, 4).val()
    changed_shape = gear_solid(12, 2, 12, 4).val()
    assert original_shape.isValid() and changed_shape.isValid()
    assert original_shape.Volume() != pytest.approx(changed_shape.Volume(), rel=1e-6)
    original_assembly = build_assembly(default)
    changed_assembly = build_assembly(changed)
    assert original_assembly.children[1].loc.toTuple()[0][0] == pytest.approx(72)
    assert changed_assembly.children[1].loc.toTuple()[0][0] == pytest.approx(42)


def test_involute_point_matches_independent_fixed_reference():
    # Independently evaluated from rb(cos t + t sin t), rb(sin t - t cos t).
    x, y = involute_xy(10.0, 0.5)
    assert x == pytest.approx(11.172953311924, abs=1e-12)
    assert y == pytest.approx(0.406342576590, abs=1e-12)


def test_profile_is_deterministic_and_pressure_angle_changes_base_circle_and_flank():
    twenty = gear_profile_points(18, 2, 20)
    twenty_again = gear_profile_points(18, 2, 20)
    twenty_five = gear_profile_points(18, 2, 25)
    assert twenty == twenty_again
    assert len(twenty) == len(twenty_five)
    assert twenty != twenty_five
    # Base-circle diameter: d_b = m z cos(alpha).
    assert 36 * math.cos(math.radians(20)) == pytest.approx(33.828934348293, abs=1e-12)
    assert gear_solid(18, 2, 12, 4, 25).val().isValid()


def test_generated_spline_edges_follow_independent_involute_relation():
    # Independently evaluate actual OCCT spline-edge points at the steepest
    # sampled test case and compare to the polar involute angular relation.
    teeth, module, pressure = 18, 6.0, 30.0
    base = module * teeth * math.cos(math.radians(pressure)) / 2
    start = max(base, module * (teeth - 2.5) / 2)
    tip = module * (teeth + 2) / 2
    pitch_angle = 2 * math.pi / teeth
    inv_pressure = math.tan(math.radians(pressure)) - math.radians(pressure)
    edge_residuals = []
    for edge in gear_profile_wire(teeth, module, pressure).Edges():
        residuals = []
        for sample in range(1, 20):
            point = edge.positionAt(sample / 20)
            radius = math.hypot(point.x, point.y)
            if start + 1e-4 < radius < tip - 0.01:
                alpha = math.acos(base / radius)
                half = math.pi / (2 * teeth) + math.tan(alpha) - alpha - inv_pressure
                angle = math.atan2(point.y, point.x) % pitch_angle
                residuals.append(min(abs(angle - half), abs(angle - (pitch_angle - half))))
        if len(residuals) >= 10:
            edge_residuals.append(residuals)
    assert len(edge_residuals) == 2 * teeth
    assert max(max(values) for values in edge_residuals) < 1e-6


@pytest.mark.parametrize("teeth,module,pressure", [(8, 0.5, 14), (120, 6, 30)])
def test_involute_profile_supported_extreme_inputs(teeth, module, pressure):
    points = gear_profile_points(teeth, module, pressure)
    assert len(points) >= teeth * 2 * INVOLUTE_FLANK_STEPS


@pytest.mark.parametrize("args", [(7, 2, 20), (18, 0.1, 20), (18, 2, 31)])
def test_involute_profile_rejects_out_of_range_inputs(args):
    with pytest.raises(ValueError):
        gear_profile_points(*args)


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
