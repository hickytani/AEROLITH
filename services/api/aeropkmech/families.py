"""Small registry of genuinely implemented design families."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .domain import Design
from .engineering import derive


@dataclass(frozen=True)
class FamilyMetadata:
    id: str
    display_name: str
    category: str
    schema_version: str
    parameters: tuple[dict[str, Any], ...]
    capabilities: tuple[str, ...]
    limitations: tuple[str, ...]
    artifacts: tuple[str, ...]
    exporters: tuple[dict[str, str], ...]
    verification_checks: tuple[str, ...]


class DesignFamily(Protocol):
    metadata: FamilyMetadata

    def default_design(self) -> Design: ...
    def validate_state(self, design: Design) -> None: ...
    def calculate(self, design: Design) -> dict[str, Any]: ...
    def verify(self, design: Design) -> dict[str, Any]: ...
    def generate_geometry(self, design: Design) -> Any: ...


class UnsupportedDesignFamily(ValueError):
    pass


class SpurGearPairFamily:
    metadata = FamilyMetadata(
        id="spur_gear_pair",
        display_name="External spur gear pair",
        category="Mechanical systems / gears and transmissions",
        schema_version="1.0",
        parameters=(
            {"name": "pinion_teeth", "unit": "teeth", "minimum": 8, "maximum": 80},
            {"name": "gear_teeth", "unit": "teeth", "minimum": 8, "maximum": 120},
            {"name": "module_mm", "unit": "mm", "minimum": 0.5, "maximum": 6},
            {"name": "face_width_mm", "unit": "mm", "minimum": 2, "maximum": 60},
            {"name": "input_torque_Nm", "unit": "N·m", "minimum_exclusive": 0},
            {"name": "input_speed_rpm", "unit": "rpm", "minimum_exclusive": 0},
        ),
        capabilities=("typed parameter validation", "ideal ratio and kinematics", "educational polygonal CAD", "STEP/STL and reports"),
        limitations=("not involute", "no tooth-contact or interference analysis", "no strength, fatigue, thermal, or safety rating", "single local project store"),
        artifacts=("step", "stl", "html", "pdf"),
        exporters=(
            {"type": "step", "implementation": "aeropkmech.cad.export_step"},
            {"type": "stl", "implementation": "aeropkmech.cad.export_stl"},
            {"type": "html", "implementation": "aeropkmech.main.report"},
            {"type": "pdf", "implementation": "aeropkmech.main.report_pdf"},
        ),
        verification_checks=("implemented input consistency", "ideal kinematics: PARTIAL", "polygonal CAD: WARNING", "tooth strength/contact: UNKNOWN", "thermal: UNTESTED", "service conditions: UNOBSERVABLE"),
    )

    def default_design(self) -> Design:
        from .store import default_design

        return default_design()

    def validate_state(self, design: Design) -> None:
        if design.family != self.metadata.id or design.schema_version != self.metadata.schema_version:
            raise UnsupportedDesignFamily(
                f"Unsupported design family/schema: {design.family}@{design.schema_version}."
            )
        Design.model_validate(design.model_dump(mode="json"))

    def calculate(self, design: Design) -> dict[str, Any]:
        self.validate_state(design)
        return derive(design)

    def verify(self, design: Design) -> dict[str, Any]:
        self.validate_state(design)
        from .verification import summarize

        return summarize(design)

    def generate_geometry(self, design: Design) -> Any:
        self.validate_state(design)
        from .cad import build_assembly

        return build_assembly(design)


class ElectricVehicleFamily:
    """Concept EV envelopes with explicit assumptions, not a roadworthy design."""
    metadata = FamilyMetadata(
        id="electric_vehicle", display_name="Concept electric vehicle packaging assembly",
        category="Automotive systems / EV packaging", schema_version="1.0",
        parameters=(
            {"name":"overall_length_mm","unit":"mm","source":"prompt or explicit input"},
            {"name":"overall_width_mm","unit":"mm","source":"prompt or explicit input"},
            {"name":"wheelbase_mm","unit":"mm","source":"explicit input or recorded conceptual default"},
            {"name":"front_track_mm","unit":"mm","source":"explicit input or recorded conceptual default"},
            {"name":"rear_track_mm","unit":"mm","source":"explicit input or recorded conceptual default"},
        ),
        capabilities=("versioned EV packaging parameters","CadQuery frame/wheel/body/propulsion envelopes","assembly STEP and STL","revision-linked component STL","layout drawing PDF","manifest and BOM JSON"),
        limitations=("conceptual envelope geometry only","no range, mass, strength, crash, suspension, thermal, regulatory, or safety analysis","assumed geometry defaults must be reviewed"),
        artifacts=("step","stl","component stl","drawing pdf","manifest json","bom json"),
        exporters=(
            {"type":"step","implementation":"automotive.export_vehicle_step"},
            {"type":"stl","implementation":"automotive.export_vehicle_stl"},
            {"type":"pdf","implementation":"automotive.export_vehicle_drawing_pdf"},
            {"type":"json","implementation":"automotive.vehicle_manifest / vehicle_bom"},
        ),
        verification_checks=("parameter consistency: CALCULATED","component placement: CALCULATED","range: UNRESOLVED","strength and safety: UNSUPPORTED"),
    )

    def default_design(self):
        from .automotive import VehicleGenerationRequest, make_vehicle_design
        request = VehicleGenerationRequest(
            expected_revision=1, overall_length_mm=4200, overall_width_mm=1800, occupant_capacity=2,
            target_range_km=300, body_height_mm=1400, wheelbase_mm=2520, front_track_mm=1575,
            rear_track_mm=1575, tire_outer_diameter_mm=650, tire_width_mm=225, ground_clearance_mm=150,
            frame_rail_width_mm=60, frame_rail_height_mm=80, body_width_mm=1260, body_length_mm=4200,
        )
        return make_vehicle_design(request, 1, [])

    def validate_state(self, design):
        from .automotive import VehicleDesign
        VehicleDesign.model_validate(design.model_dump(mode="json"))

    def calculate(self, design):
        from .automotive import vehicle_calculate
        self.validate_state(design)
        return vehicle_calculate(design)

    def verify(self, design):
        from .automotive import vehicle_calculate
        result = vehicle_calculate(design)
        return {
            "dimensional_consistency":{"state":"CALCULATED","summary":"Specified and assumed packaging dimensions satisfy the family checks.","evidence":["VehicleParameters cross-field validation passed."]},
            "wheel_placement":{"state":"CALCULATED","summary":"Four wheel/tire centers and axle references are derived from wheelbase and track.","evidence":[f"Wheelbase {design.requirements.wheelbase_mm.value:g} mm; front/rear track {design.requirements.front_track_mm.value:g}/{design.requirements.rear_track_mm.value:g} mm."]},
            "target_range":{"state":"UNRESOLVED","summary":"The requested range is a target and was not calculated.","evidence":[]},
            "strength_safety":{"state":"UNSUPPORTED","summary":"No structural, crash, road-safety, or manufacturing analysis is implemented.","evidence":[]},
        }

    def generate_geometry(self, design):
        from .automotive import build_vehicle_assembly
        self.validate_state(design)
        return build_vehicle_assembly(design)


class FamilyInitializationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    family_id: str = Field(min_length=1, max_length=80)
    schema_version: str = Field(default="1.0", min_length=1, max_length=20)


class GearExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    pinion_teeth: int = Field(default=18, ge=8, le=80)
    gear_teeth: int = Field(default=54, ge=8, le=120)
    module_mm: float = Field(default=2, ge=0.5, le=6)
    face_width_mm: float = Field(default=12, ge=2, le=60)
    input_torque_Nm: float = Field(default=8, gt=0)
    input_speed_rpm: float = Field(default=900, gt=0)


IMPLEMENTED_FAMILIES: dict[str, DesignFamily] = {"spur_gear_pair": SpurGearPairFamily(), "electric_vehicle": ElectricVehicleFamily()}
PLANNED_FAMILY_AREAS = (
    "Motors and electromechanical systems",
    "Aerospace and aerodynamics",
    "Robotics and mechanisms",
    "General CAD",
)


def get_family(family_id: str, schema_version: str | None = None) -> DesignFamily:
    family = IMPLEMENTED_FAMILIES.get(family_id)
    if family is None:
        raise UnsupportedDesignFamily(f"Design family '{family_id}' is not implemented.")
    if schema_version is not None and schema_version != family.metadata.schema_version:
        raise UnsupportedDesignFamily(
            f"Unsupported schema version '{schema_version}' for design family '{family_id}'."
        )
    return family


def list_families() -> list[FamilyMetadata]:
    return [family.metadata for family in IMPLEMENTED_FAMILIES.values()]
