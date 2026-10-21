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


def test_complete_spur_gear_request_produces_reviewable_connected_specification():
    result = propose_specification(
        "Design an external spur gear pair: pinion 18 teeth and driven gear 54 teeth, "
        "module 2 mm, face width 12 mm, input torque 8 N·m, input speed 900 rpm."
    )
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
    ids = {item.id for item in result.components}
    assert {"frame-rail-left", "front-axle-reference", "body-envelope", "battery-pack-envelope", "traction-motor-envelope", "inverter-envelope", "reduction-drive-envelope"} <= ids
    assert {("battery-pack-envelope", "inverter-envelope")} <= {
        (item.source_component, item.target_component) for item in result.connections
    }
    assert result.connections
    assert "layout drawing PDF" in result.supported_artifacts
    assert result.can_commit is True
    assert any("wheelbase" in question for question in result.unresolved_questions)


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
