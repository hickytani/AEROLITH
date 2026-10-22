import pytest

from aeropkmech.intelligence import extract_local, propose_specification


def test_extracts_supported_spur_gear_requirements_without_applying_them():
    result = extract_local(
        "18 teeth pinion and 54 tooth driven gear, module 2 mm, face width 12 mm, input torque 8 N·m, input speed 900 rpm"
    )
    assert result.parsed is True
    assert result.proposal.pinion_teeth == 18
    assert result.proposal.gear_teeth == 54
    assert result.proposal.gear_ratio == 3
    assert result.proposal.input_torque_Nm == 8
    assert result.proposal.input_speed_rpm == 900
    assert result.requires_confirmation is True


def test_missing_values_are_reported_and_never_filled_from_demo_defaults():
    result = extract_local("I need a spur gear pair with input speed 900 rpm")
    assert result.parsed is False
    assert result.proposal.pinion_teeth is None
    assert result.proposal.gear_teeth is None
    assert "module_mm" in result.missing
    assert "input_speed_rpm" not in result.missing


def test_inconsistent_stated_ratio_is_flagged():
    result = extract_local("18 teeth pinion, 54 teeth driven gear, ratio 4:1")
    assert result.parsed is False
    assert result.conflicts


def test_torque_unit_conversion_is_explicit():
    result = extract_local("input torque 8000 Nmm")
    assert result.proposal.input_torque_Nm == 8


@pytest.mark.parametrize(
    "module,width,expected_module,expected_width",
    [("2 mm", "12 mm", 2, 12), ("0.2 cm", "1.2 cm", 2, 12), ("0.002 m", "0.012 m", 2, 12), ("0.0787401575 in", "0.472440945 in", 2, 12)],
)
def test_gear_lengths_are_normalized_to_mm_and_keep_literal_evidence(module, width, expected_module, expected_width):
    result = extract_local(f"External spur gear pair, module {module}, face width {width}")
    assert result.proposal.module_mm == pytest.approx(expected_module, abs=1e-8)
    assert result.proposal.face_width_mm == pytest.approx(expected_width, abs=1e-8)
    assert result.evidence["module_mm"] == f"module {module}"
    assert result.evidence["face_width_mm"] == f"face width {width}"
    proposal = propose_specification(f"External spur gear pair, module {module}, face width {width}")
    module_parameter = next(item for item in proposal.parameters if item.name == "module_mm")
    assert module_parameter.value == pytest.approx(expected_module, abs=1e-8)
    assert module_parameter.unit == "mm"
    assert module_parameter.evidence == f"module {module}"


def test_gear_length_unit_conflicts_and_unsupported_units_are_explicit():
    conflict = extract_local("External spur gear pair, module 2 mm and module 0.3 cm")
    assert conflict.proposal.module_mm == 2
    assert any("Conflicting explicit values for module_mm" in item for item in conflict.conflicts)
    unsupported = extract_local("External spur gear pair, module 0.08 ft, face width 12 mm")
    assert unsupported.proposal.module_mm is None
    assert any("Unsupported length unit for module_mm" in item for item in unsupported.conflicts)


def test_pressure_angle_is_extracted_or_explicitly_defaulted_and_invalid_ranges_stay_visible():
    implicit_units = extract_local("spur gear pair pressure angle 25")
    assert implicit_units.proposal.pressure_angle_deg == 25
    assert implicit_units.evidence["pressure_angle_deg"] == "pressure angle 25"
    explicit_units = extract_local("spur gear pair pressure angle = 22.5 degrees")
    assert explicit_units.proposal.pressure_angle_deg == 22.5
    defaulted = propose_specification("external spur gear pair")
    angle = next(item for item in defaulted.parameters if item.name == "pressure_angle_deg")
    assert angle.value == 20 and angle.source == "assumed" and angle.status == "ASSUMED"
    invalid = extract_local("spur gear pair pressure angle 35 degrees")
    assert invalid.proposal.pressure_angle_deg is None
    assert any("pressure_angle_deg value" in issue for issue in invalid.conflicts)


def test_complete_spur_gear_request_produces_reviewable_connected_specification():
    prompt = (
        "Design an external spur gear pair: pinion 18 teeth and driven gear 54 teeth, "
        "module 2 mm, face width 12 mm, input torque 8 N·m, input speed 900 rpm."
    )
    result = propose_specification(prompt)
    assert result.intent == "SUPPORTED_SPUR_GEAR_PAIR"
    assert result.family_id == "spur_gear_pair"
    assert result.can_commit is True
    assert result.requires_confirmation is True
    assert result.provider == "deterministic-patterns-v1"
    assert [(item.id, item.kind) for item in result.components] == [
        ("gear-pair", "assembly"), ("pinion", "component"), ("gear", "component"),
    ]
    assert result.connections[0].relationship == "external_gear_mesh"
    ratio = next(item for item in result.parameters if item.name == "gear_ratio")
    assert ratio.value == 3
    assert ratio.source == "derived"
    assert ratio.status == "DERIVED"
    assert ratio.canonical_target == "requirements.gear_ratio"
    assert ratio.source_span is None
    module = next(item for item in result.parameters if item.name == "module_mm")
    assert prompt[module.source_span["start"]:module.source_span["end"]] == module.evidence
    assert module.quantity.schema_version == "1.0"
    assert module.quantity.quantity_kind == "length"
    assert module.quantity.canonical_unit == "mm"
    assert module.quantity.source_span == module.source_span
    assert module.affected_components == ["pinion", "gear", "gear-pair"]
    assert {"STEP", "STL", "HTML report", "PDF report", "dimensioned gear reference layout PDF"} == set(result.supported_artifacts)


def test_incomplete_request_does_not_fill_from_default_and_keeps_reviewable_structure():
    result = propose_specification("Design an external spur gear pair with input speed 900 rpm")
    parameters = {item.name: item for item in result.parameters}
    assert result.can_commit is False
    assert parameters["input_speed_rpm"].value == 900
    assert parameters["input_speed_rpm"].source == "user-provided"
    assert parameters["pinion_teeth"].value is None
    assert parameters["module_mm"].value is None
    assert result.unresolved_questions
    assert len(result.components) == 3
    assert result.connections[0].status == "NEEDS_INPUT"


def test_conflicting_and_out_of_range_requests_are_explicit():
    conflict = propose_specification("External spur gear pair, pinion 18 teeth, driven gear 54 teeth, ratio 4:1")
    assert conflict.can_commit is False
    assert conflict.conflicts
    invalid = propose_specification("External spur gear pair, pinion 7 teeth")
    invalid_pinion = next(item for item in invalid.parameters if item.name == "pinion_teeth")
    assert invalid_pinion.status == "INVALID"
    assert invalid.validation_issues
    assert invalid.conflicts == []
    assert invalid.can_commit is False


def test_electric_vehicle_prompt_gets_a_conceptual_graph_without_fake_geometry():
    result = propose_specification("Design an electric vehicle with a spur gear pair")
    assert result.intent == "CONCEPTUAL_ELECTRIC_VEHICLE"
    assert result.family_id is None
    assert result.components
    assert all(item.status == "CONCEPTUAL_ONLY" and not item.generator_available for item in result.components)
    assert result.supported_artifacts == []
    assert result.unresolved_questions
    assert any(item.id == "vehicle-assembly" and item.kind == "assembly" for item in result.components)
    assert result.can_commit is False


def test_two_seat_electric_sports_car_prompt_extracts_dimensions_and_decomposes_systems():
    result = propose_specification(
        "Generate a two-seater sports car, electric powered, 4.2 m long, 1.8 m wide, "
        "with a 300 km range. Include the necessary mechanical and electrical systems."
    )
    assert result.system_name == "2-seat electric sports car"
    assert result.domain == "automotive"
    assert result.generation_status == "GEOMETRY_REVIEW"
    parameters = {item.name: item for item in result.parameters}
    assert parameters["occupant_capacity"].value == 2
    assert parameters["overall_length_mm"].value == 4200
    assert parameters["overall_width_mm"].value == 1800
    assert parameters["target_range_km"].value == 300
    assert parameters["propulsion_type"].value == "electric"
    assert parameters["overall_length_mm"].source == "user-provided"
    assert parameters["overall_length_mm"].quantity.value == 4200
    assert parameters["overall_length_mm"].quantity.input_value == 4.2
    assert parameters["overall_length_mm"].quantity.input_unit == "m"
    assert parameters["overall_length_mm"].quantity.source_span == parameters["overall_length_mm"].source_span
    ids = {item.id for item in result.components}
    assert {"frame-rail-left", "front-axle-reference", "body-envelope", "battery-pack-envelope", "traction-motor-envelope", "inverter-envelope", "reduction-drive-envelope"} <= ids
    assert {("battery-pack-envelope", "inverter-envelope")} <= {
        (item.source_component, item.target_component) for item in result.connections
    }
    assert result.connections
    assert "layout drawing PDF" in result.supported_artifacts
    assert result.can_commit is True
    assert any("wheelbase" in question for question in result.unresolved_questions)
    assert result.completion_scope == "PARTIAL_WITH_UNSUPPORTED_REQUESTS"
    assert any("complete mechanical/electrical systems" in item for item in result.unsupported_requests)
    assert all(item.status == "CONCEPTUAL_ONLY" for item in result.connections)
    tire = next(item for item in result.components if item.id == "tire-front-left")
    assert "tire_outer_diameter_mm" in tire.parameter_refs


def test_unmatched_non_electric_car_does_not_claim_a_vehicle_architecture():
    result = propose_specification("Generate a two-seat sports car, 4.2 m long")
    assert result.intent == "UNSUPPORTED_OR_UNCLEAR"
    assert result.components == []
    assert result.family_id is None


def test_vehicle_units_and_out_of_scope_dimensions_remain_explicit():
    result = propose_specification("Electric vehicle, 4.2 metres long, 180 centimetres wide, 300 km range")
    parameters = {item.name: item for item in result.parameters}
    assert parameters["overall_length_mm"].value == 4200
    assert parameters["overall_width_mm"].value == 1800
    out_of_range = propose_specification("Electric sports car 42 m long")
    length = next(item for item in out_of_range.parameters if item.name == "overall_length_mm")
    assert length.value == 42000
    assert length.status == "INVALID"
    assert out_of_range.validation_issues


def test_conflicting_duplicate_parameters_and_incompatible_units_are_not_silently_accepted():
    gear = propose_specification("External spur gear pair, pinion 18 teeth and pinion 20 teeth, driven gear 54 teeth, module 2 mm, face width 12 mm, torque 8 Nm, speed 900 rpm")
    assert not gear.can_commit
    assert any("Conflicting explicit values for pinion_teeth" in item for item in gear.conflicts)

    vehicle = propose_specification("Two-seater electric sports car, 4.2 m long, 4.5 m long, 1.8 m wide, 300 km range")
    assert not vehicle.can_commit
    assert any("Conflicting explicit values for overall_length_mm" in item for item in vehicle.conflicts)

    unsupported_unit = propose_specification("Two-seater electric sports car, 14 ft long, 6 ft wide, 300 km range")
    assert unsupported_unit.can_commit is False
    assert any("Unsupported dimension unit" in item for item in unsupported_unit.unsupported_requests)
    assert next(item for item in unsupported_unit.parameters if item.name == "overall_length_mm").value is None

    propulsion = propose_specification("Two-seater electric hybrid sports car, 4.2 m long, 1.8 m wide, 300 km range")
    assert propulsion.can_commit is False
    assert any("Conflicting propulsion" in item for item in propulsion.conflicts)

    packaging = propose_specification("Two-seater electric sports car, 4.2 m long, 1.8 m wide, 300 km range, wheelbase 3500 mm, tire diameter 1000 mm")
    assert packaging.can_commit is False
    assert any("Cross-field packaging validation failed" in item for item in packaging.validation_issues)
