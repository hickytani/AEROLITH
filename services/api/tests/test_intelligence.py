from aeropkmech.intelligence import extract_local


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
