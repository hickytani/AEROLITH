import math
from pathlib import Path
import cadquery as cq
from OCP.StlAPI import StlAPI_Reader
from OCP.TopoDS import TopoDS_Shape
import pytest
from pydantic import ValidationError

from aeropkmech.cad import build_assembly, export_step, export_stl, gear_solid
from aeropkmech.domain import Design, Requirements
from aeropkmech.store import default_design


def test_measure_solid_before_after_bore_diameter_change():
    """Verify that bore diameter edit directly changes solid inner radius and volume."""
    teeth, module, width = 18, 2.0, 15.0
    bore_small = 6.0
    bore_large = 14.0

    solid_small = gear_solid(teeth, module, width, bore_small).val()
    solid_large = gear_solid(teeth, module, width, bore_large).val()

    assert solid_small.isValid() and solid_large.isValid()
    vol_small = solid_small.Volume()
    vol_large = solid_large.Volume()
    assert vol_large < vol_small

    # Exact expected material volume removed by expanding cylinder
    expected_vol_diff = math.pi * ((bore_large / 2) ** 2 - (bore_small / 2) ** 2) * width
    actual_vol_diff = vol_small - vol_large
    assert actual_vol_diff == pytest.approx(expected_vol_diff, rel=1e-4)

    # Inspect inner edge radius directly in OpenCASCADE
    bore_edges_small = [edge.radius() for edge in solid_small.Edges() if edge.geomType() == "CIRCLE" and edge.radius() < 10.0]
    bore_edges_large = [edge.radius() for edge in solid_large.Edges() if edge.geomType() == "CIRCLE" and edge.radius() < 10.0]
    assert all(r == pytest.approx(bore_small / 2, abs=1e-6) for r in bore_edges_small)
    assert all(r == pytest.approx(bore_large / 2, abs=1e-6) for r in bore_edges_large)


def test_keyway_topology_depth_and_placement_on_positive_y():
    """Verify that keyway slot is located on the +Y side of the bore at the specified depth."""
    teeth, module, width = 18, 2.0, 15.0
    bore = 12.0
    kw_width = 4.0
    kw_depth = 2.5

    solid_plain = gear_solid(teeth, module, width, bore).val()
    solid_keyed = gear_solid(teeth, module, width, bore, keyway_width_mm=kw_width, keyway_depth_mm=kw_depth).val()

    assert solid_plain.isValid() and solid_keyed.isValid()
    assert solid_keyed.Volume() < solid_plain.Volume()

    # In solid_keyed, examine edges:
    # 1. The keyway slot ceiling lines are located on the +Y side at y = bore/2 + kw_depth = 6.0 + 2.5 = 8.5 mm
    ceiling_lines = [
        e for e in solid_keyed.Edges()
        if e.geomType() == "LINE" and abs(e.startPoint().y - (bore / 2 + kw_depth)) < 1e-3 and abs(e.endPoint().y - (bore / 2 + kw_depth)) < 1e-3
    ]
    assert len(ceiling_lines) >= 2
    # Verify the horizontal line segment length equals keyway width (4.0 mm)
    slot_width_lines = [e for e in ceiling_lines if abs(e.Length() - kw_width) < 1e-3]
    assert len(slot_width_lines) == 2  # one on each Z end-face

    # 2. On the -Y side, the circular bore remains intact with radius = bore/2 = 6.0 mm
    circle_edges = [e for e in solid_keyed.Edges() if e.geomType() == "CIRCLE"]
    assert len(circle_edges) >= 2
    assert all(abs(e.radius() - (bore / 2)) < 1e-6 for e in circle_edges)


def test_boundary_keyway_width_vs_bore_diameter():
    """Verify boundary conditions: width strictly less than bore passes; width >= bore fails."""
    bore = 10.0
    design = default_design()

    # Valid boundary: keyway width = bore - 0.01 mm (9.99 mm) should be valid in Design
    valid_design = Design.model_validate({
        **design.model_dump(mode="json"),
        "parameter_quantities": {},
        "parameter_records": {},
        "requirements": {
            **design.requirements.model_dump(mode="json"),
            "bore_diameter_mm": bore,
            "keyway_width_mm": bore - 0.01,
            "keyway_depth_mm": 2.0,
        }
    })
    assert valid_design.requirements.keyway_width_mm == pytest.approx(9.99)

    # Solid generation with close boundary succeeds
    solid = gear_solid(20, 2.0, 20.0, bore, keyway_width_mm=bore - 0.01, keyway_depth_mm=2.0)
    assert solid.val().isValid()

    # Boundary violation: width == bore diameter must fail Design cross-field invariant
    with pytest.raises(ValidationError) as exc_info:
        Design.model_validate({
            **design.model_dump(mode="json"),
            "parameter_quantities": {},
            "parameter_records": {},
            "requirements": {
                **design.requirements.model_dump(mode="json"),
                "bore_diameter_mm": bore,
                "keyway_width_mm": bore,
                "keyway_depth_mm": 2.0,
            }
        })
    assert "strictly less than bore diameter" in str(exc_info.value)


def test_failed_boolean_or_invalid_dimensions_raises_without_corrupting_state():
    """Verify that invalid boolean cutter geometry raises safely without mutating state."""
    design = default_design()
    initial_dump = design.model_dump(mode="json")

    # Invalid non-positive dimensions for keyway slot in CAD solid construction must raise ValueError
    with pytest.raises(ValueError) as exc_val:
        gear_solid(18, 2.0, 15.0, 10.0, keyway_width_mm=-5.0, keyway_depth_mm=2.0)
    assert "must be strictly positive" in str(exc_val.value)

    # Bore exceeding safe rim thickness must fail validation before CAD generation
    with pytest.raises(ValidationError) as exc_rim:
        bad_req = design.requirements.model_copy(update={"bore_diameter_mm": 35.0})
        Design.model_validate({**design.model_dump(mode="json"), "requirements": bad_req.model_dump(mode="json")})
    assert "safe rim thickness" in str(exc_rim.value)

    # State remains unaffected
    assert design.model_dump(mode="json") == initial_dump


def test_step_and_stl_export_consistency_with_bore_and_keyway(tmp_path):
    """Verify round-trip export of STEP and STL with user-specified bore and keyway geometry."""
    design = default_design()
    design.requirements.bore_diameter_mm = 12.0
    design.requirements.keyway_width_mm = 4.0
    design.requirements.keyway_depth_mm = 2.0

    step_file = tmp_path / "test_keyed.step"
    stl_file = tmp_path / "test_keyed.stl"
    export_step(design, step_file)
    export_stl(design, stl_file)

    assert step_file.exists() and step_file.stat().st_size > 0
    assert stl_file.exists() and stl_file.stat().st_size > 0

    # Re-import STEP into CadQuery and verify geometry
    imported_step = cq.importers.importStep(str(step_file)).val()
    assert imported_step.isValid()
    assert len(imported_step.Solids()) == 2
    expected_assembly_vol = sum(c.obj.val().Volume() for c in build_assembly(design).children)
    assert imported_step.Volume() == pytest.approx(expected_assembly_vol, rel=1e-7)

    # Re-import STL via OpenCASCADE TopoDS_Shape
    mesh_shape = TopoDS_Shape()
    assert StlAPI_Reader().Read(mesh_shape, str(stl_file))
    assert not mesh_shape.IsNull()
    cq_mesh = cq.Shape.cast(mesh_shape)
    assert len(cq_mesh.Faces()) > 100
