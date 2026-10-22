import pytest
from pydantic import ValidationError

from aeropkmech.domain import Design
from aeropkmech.quantities import EngineeringQuantity, QuantityUnitError, convert_quantity, quantity_from_canonical
from aeropkmech.store import default_design
from aeropkmech.contracts import ParameterRecord


@pytest.mark.parametrize(
    "value,unit,expected",
    [(1, "mm", 1), (0.1, "cm", 1), (0.001, "m", 1), (1 / 25.4, "in", 1)],
)
def test_independent_length_conversion_references(value, unit, expected):
    # Fixed SI/defined-unit references: 1 cm=10 mm; 1 in=25.4 mm.
    converted, canonical, factor = convert_quantity(value, unit, "length")
    assert canonical == "mm"
    assert converted == pytest.approx(expected, abs=1e-12)
    assert factor > 0


@pytest.mark.parametrize(
    "value,unit,kind,expected,canonical",
    [(180, "deg", "angle", 180, "deg"), (3.141592653589793, "rad", "angle", 180, "deg"),
     (8000, "Nmm", "torque", 8, "N·m"), (60, "rpm", "rotational_speed", 60, "rpm"),
     (1, "mile", "range", 1.609344, "km")],
)
def test_supported_quantity_dimensions_and_conversions(value, unit, kind, expected, canonical):
    converted, canonical_unit, _ = convert_quantity(value, unit, kind)
    assert canonical_unit == canonical
    assert converted == pytest.approx(expected, abs=1e-10)


def test_rejects_unsupported_units_incompatible_dimensions_and_non_finite_values():
    with pytest.raises(QuantityUnitError):
        convert_quantity(1, "ft", "length")
    with pytest.raises(QuantityUnitError):
        convert_quantity(1, "km", "torque")
    with pytest.raises(ValueError):
        convert_quantity(float("inf"), "mm", "length")


def test_quantity_contract_keeps_conversion_provenance_and_checks_bounds():
    quantity = quantity_from_canonical(
        1, "mm", "length", "user-provided", evidence="module 0.1 cm",
        source_span={"start": 0, "end": 13, "text": "module 0.1 cm"}, minimum=0.5, maximum=6,
    )
    assert quantity.schema_version == "1.0"
    assert quantity.value == 1
    assert quantity.canonical_unit == "mm"
    assert quantity.input_value == 0.1
    assert quantity.input_unit == "cm"
    assert quantity.conversion_factor == 10
    assert quantity.evidence == "module 0.1 cm"
    assert EngineeringQuantity.model_validate_json(quantity.model_dump_json()) == quantity
    with pytest.raises(ValidationError):
        EngineeringQuantity(quantity_kind="length", value=7, canonical_unit="mm", source="user-provided", minimum=0.5, maximum=6)
    with pytest.raises(ValidationError):
        EngineeringQuantity.model_validate({**quantity.model_dump(mode="json"), "schema_version": "99.0"})


def test_legacy_gear_state_migrates_quantities_and_rejects_stale_serialized_value():
    legacy = default_design().model_dump(mode="json")
    legacy.pop("parameter_quantities")
    legacy.pop("parameter_records")
    loaded = Design.model_validate(legacy)
    assert loaded.parameter_quantities["module_mm"].value == 2
    assert loaded.parameter_quantities["module_mm"].canonical_unit == "mm"
    assert loaded.parameter_quantities["module_mm"].schema_version == "1.0"

    sourced = default_design().model_dump(mode="json")
    sourced.pop("parameter_quantities")
    sourced.pop("parameter_records")
    sourced["source_prompt"] = "external gear pair module 0.2 cm"
    sourced["requirement_sources"] = {"module_mm": "user-provided"}
    sourced["requirement_evidence"] = {"module_mm": "module 0.2 cm"}
    sourced_design = Design.model_validate(sourced)
    module = sourced_design.parameter_quantities["module_mm"]
    assert module.value == 2
    assert module.input_value == 0.2 and module.input_unit == "cm"
    assert module.evidence == "module 0.2 cm"
    assert module.source_span == {"start": 19, "end": 32, "text": "module 0.2 cm"}

    corrupt = loaded.model_dump(mode="json")
    corrupt["parameter_quantities"]["module_mm"]["value"] = 3
    with pytest.raises(ValidationError):
        Design.model_validate(corrupt)


def test_shared_parameter_records_round_trip_and_reject_broken_identity_revision_or_references():
    design = default_design()
    serialized = design.model_dump(mode="json")
    restored = Design.model_validate_json(design.model_dump_json())
    module = restored.parameter_records["module_mm"]
    assert module.id == f"{design.id}:module_mm"
    assert module.project_id == design.id
    assert module.family_id == design.family
    assert module.revision == design.revision
    assert restored.parameter_records["pinion_teeth"].component_ids == ["pinion"]
    assert restored.parameter_records["gear_ratio"].source_parameter_ids == [
        f"{design.id}:gear_teeth", f"{design.id}:pinion_teeth",
    ]

    legacy = dict(serialized)
    legacy.pop("parameter_records")
    migrated = Design.model_validate(legacy)
    assert migrated.parameter_records == design.parameter_records

    wrong_revision = dict(serialized)
    wrong_revision["parameter_records"] = {key: record.model_dump(mode="json") for key, record in design.parameter_records.items()}
    wrong_revision["parameter_records"]["module_mm"]["revision"] += 1
    with pytest.raises(ValidationError):
        Design.model_validate(wrong_revision)

    wrong_reference = dict(serialized)
    wrong_reference["parameter_records"] = {key: record.model_dump(mode="json") for key, record in design.parameter_records.items()}
    wrong_reference["parameter_records"]["pinion_teeth"]["component_ids"] = ["missing-component"]
    with pytest.raises(ValidationError):
        Design.model_validate(wrong_reference)

    with pytest.raises(ValidationError):
        ParameterRecord.model_validate({**module.model_dump(mode="json"), "schema_version": "99.0"})
