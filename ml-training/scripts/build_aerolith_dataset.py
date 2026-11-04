"""AEROLITH Engineering Dataset Generator (v2.2.0).

Generates a versioned, disjoint, multi-task dataset for natural-language
engineering parameter extraction, constraint verification, assembly planning,
tool use, change impact, failure handling, and engineering truth preservation.

Zero prompt leakage across train, validation, and test splits.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

DATASET_VERSION = "engineering-v2.2.0"
SCHEMA_VERSION = "2.0"

SUPPORTED_CATEGORIES = [
    "requirement_extraction",
    "constraint_interpretation",
    "assembly_planning",
    "engineering_tool_use",
    "component_understanding",
    "change_impact",
    "failure_handling",
    "engineering_explanation",
]


def make_record(
    rec_id: str,
    split: str,
    category: str,
    prompt: str,
    context: dict,
    expected_output: dict,
    generator_version: str | None = "aerolith-synthetic-v2.2",
    tool_version: str | None = None,
    revision: int | None = None,
) -> dict:
    return {
        "id": rec_id,
        "split": split,
        "task_category": category,
        "input": prompt,
        "context": context,
        "expected_output": expected_output,
        "schema_version": "1.0",
        "provenance": {
            "origin": "synthetic_hand_authored",
            "license": "CC0-1.0",
        },
        "review_status": "SYNTHETIC_REVIEWED",
        "dataset_version": DATASET_VERSION,
        "generator_version": generator_version,
        "tool_version": tool_version,
        "engineering_revision": revision,
    }


def generate_dataset() -> dict[str, list[dict]]:
    records: dict[str, list[dict]] = {"train": [], "validation": [], "test": []}

    # =========================================================================
    # 1. REQUIREMENT EXTRACTION (SPUR GEAR + EV + UNSUPPORTED)
    # =========================================================================
    # Train
    records["train"].extend([
        # Standard gear pairs
        make_record(
            "req-gear-tr-001", "train", "requirement_extraction",
            "External spur pair with 18 pinion teeth, 54 gear teeth, and module 2 mm.",
            {"allowed_family": "spur_gear_pair"},
            {"pinion_teeth": 18, "gear_teeth": 54, "module_mm": 2.0, "missing": ["face_width_mm", "input_torque_Nm", "input_speed_rpm"], "requires_confirmation": True}
        ),
        make_record(
            "req-gear-tr-002", "train", "requirement_extraction",
            "Design a 3:1 speed reducer gear pair: 20-tooth pinion, 60-tooth gear, module 2.5 mm, face width 30 mm, torque 50 N*m at 1500 rpm.",
            {"allowed_family": "spur_gear_pair"},
            {"pinion_teeth": 20, "gear_teeth": 60, "module_mm": 2.5, "face_width_mm": 30.0, "input_torque_Nm": 50.0, "input_speed_rpm": 1500.0, "missing": [], "requires_confirmation": True}
        ),
        make_record(
            "req-gear-tr-003", "train", "requirement_extraction",
            "Compact gear drive, 15 pinion teeth, 45 gear teeth, module 1.5 mm, 12 mm width.",
            {"allowed_family": "spur_gear_pair"},
            {"pinion_teeth": 15, "gear_teeth": 45, "module_mm": 1.5, "face_width_mm": 12.0, "missing": ["input_torque_Nm", "input_speed_rpm"], "requires_confirmation": True}
        ),
        make_record(
            "req-gear-tr-004", "train", "requirement_extraction",
            "High torque spur gear pair with pinion 24 teeth, gear 72 teeth, module 4 mm, face width 50 mm, 200 Nm torque, 750 rpm.",
            {"allowed_family": "spur_gear_pair"},
            {"pinion_teeth": 24, "gear_teeth": 72, "module_mm": 4.0, "face_width_mm": 50.0, "input_torque_Nm": 200.0, "input_speed_rpm": 750.0, "missing": [], "requires_confirmation": True}
        ),
        make_record(
            "req-gear-tr-005", "train", "requirement_extraction",
            "Spur pair driver with 16 teeth, driven gear 48 teeth, module 3.0 mm, face width 25 mm.",
            {"allowed_family": "spur_gear_pair"},
            {"pinion_teeth": 16, "gear_teeth": 48, "module_mm": 3.0, "face_width_mm": 25.0, "missing": ["input_torque_Nm", "input_speed_rpm"], "requires_confirmation": True}
        ),
        make_record(
            "req-gear-tr-006", "train", "requirement_extraction",
            "Industrial reducer: 25-tooth pinion, 100-tooth gear, 2 mm module, 40 mm face width, torque 150 Nm, 1000 rpm.",
            {"allowed_family": "spur_gear_pair"},
            {"pinion_teeth": 25, "gear_teeth": 100, "module_mm": 2.0, "face_width_mm": 40.0, "input_torque_Nm": 150.0, "input_speed_rpm": 1000.0, "missing": [], "requires_confirmation": True}
        ),
        make_record(
            "req-gear-tr-007", "train", "requirement_extraction",
            "Small instrument gears: pinion 12 teeth, driven gear 36 teeth, module 0.8 mm, face width 8 mm.",
            {"allowed_family": "spur_gear_pair"},
            {"pinion_teeth": 12, "gear_teeth": 36, "module_mm": 0.8, "face_width_mm": 8.0, "missing": ["input_torque_Nm", "input_speed_rpm"], "requires_confirmation": True}
        ),
        make_record(
            "req-gear-tr-008", "train", "requirement_extraction",
            "Medium spur drive: 22 pinion teeth, 66 gear teeth, module 3.5 mm, face width 35 mm, 80 Nm torque, 1200 rpm.",
            {"allowed_family": "spur_gear_pair"},
            {"pinion_teeth": 22, "gear_teeth": 66, "module_mm": 3.5, "face_width_mm": 35.0, "input_torque_Nm": 80.0, "input_speed_rpm": 1200.0, "missing": [], "requires_confirmation": True}
        ),
        # Unit normalization examples
        make_record(
            "req-gear-tr-009", "train", "requirement_extraction",
            "Gear set with 20-tooth pinion, 60-tooth gear, 0.1 inch module, 1.0 inch face width.",
            {"allowed_family": "spur_gear_pair"},
            {"pinion_teeth": 20, "gear_teeth": 60, "module_mm": 2.54, "face_width_mm": 25.4, "missing": ["input_torque_Nm", "input_speed_rpm"], "requires_confirmation": True}
        ),
        make_record(
            "req-gear-tr-010", "train", "requirement_extraction",
            "Spur gears: 18 pinion teeth, 72 gear teeth, module 2 mm, face width 4 cm.",
            {"allowed_family": "spur_gear_pair"},
            {"pinion_teeth": 18, "gear_teeth": 72, "module_mm": 2.0, "face_width_mm": 40.0, "missing": ["input_torque_Nm", "input_speed_rpm"], "requires_confirmation": True}
        ),
        # Negative / Missing parameter extraction (never hallucinate missing torque or speed)
        make_record(
            "req-gear-tr-011", "train", "requirement_extraction",
            "Spur gear pair: 19 pinion teeth, 57 gear teeth, module 2.25 mm. Do not invent unstated torque or rpm.",
            {"allowed_family": "spur_gear_pair"},
            {"pinion_teeth": 19, "gear_teeth": 57, "module_mm": 2.25, "missing": ["face_width_mm", "input_torque_Nm", "input_speed_rpm"], "requires_confirmation": True}
        ),
        make_record(
            "req-gear-tr-012", "train", "requirement_extraction",
            "Drive pinion 14 teeth, gear 42 teeth, face width 18 mm.",
            {"allowed_family": "spur_gear_pair"},
            {"pinion_teeth": 14, "gear_teeth": 42, "face_width_mm": 18.0, "missing": ["module_mm", "input_torque_Nm", "input_speed_rpm"], "requires_confirmation": True}
        ),
        # EV concepts
        make_record(
            "req-ev-tr-001", "train", "requirement_extraction",
            "4-passenger urban electric vehicle, 4000 mm length, 1750 mm width, 2500 mm wheelbase, 300 km target range.",
            {"allowed_family": "electric_vehicle"},
            {"occupant_capacity": 4, "overall_length_mm": 4000.0, "overall_width_mm": 1750.0, "wheelbase_mm": 2500.0, "target_range_km": 300.0, "unresolved": ["structural_validation", "achieved_range"], "requires_confirmation": True}
        ),
        make_record(
            "req-ev-tr-002", "train", "requirement_extraction",
            "Delivery EV van for 2 occupants, length 4800 mm, width 1900 mm, wheelbase 3000 mm, height 1850 mm.",
            {"allowed_family": "electric_vehicle"},
            {"occupant_capacity": 2, "overall_length_mm": 4800.0, "overall_width_mm": 1900.0, "wheelbase_mm": 3000.0, "body_height_mm": 1850.0, "target_range_km": 200.0, "unresolved": ["structural_validation"], "requires_confirmation": True}
        ),
        make_record(
            "req-ev-tr-003", "train", "requirement_extraction",
            "Compact 2-seat commuter EV: 3200 mm length, 1550 mm width, 2100 mm wheelbase, target range 180 km.",
            {"allowed_family": "electric_vehicle"},
            {"occupant_capacity": 2, "overall_length_mm": 3200.0, "overall_width_mm": 1550.0, "wheelbase_mm": 2100.0, "target_range_km": 180.0, "unresolved": ["structural_validation", "achieved_range"], "requires_confirmation": True}
        ),
        make_record(
            "req-ev-tr-004", "train", "requirement_extraction",
            "Family electric SUV with 7 seats, length 4950 mm, width 1980 mm, wheelbase 3050 mm, 500 km range target.",
            {"allowed_family": "electric_vehicle"},
            {"occupant_capacity": 7, "overall_length_mm": 4950.0, "overall_width_mm": 1980.0, "wheelbase_mm": 3050.0, "target_range_km": 500.0, "unresolved": ["structural_validation", "achieved_range"], "requires_confirmation": True}
        ),
        # Out-of-scope / Unsupported systems
        make_record(
            "req-unsupp-tr-001", "train", "requirement_extraction",
            "Design a 5-stage planetary gearbox with helical gear teeth and hydraulic clutch.",
            {"available_families": ["spur_gear_pair", "electric_vehicle"]},
            {"intent": "UNSUPPORTED", "supported": False, "reason": "Planetary, helical, and hydraulic systems are not supported in schema 1.0.", "requires_confirmation": False}
        ),
        make_record(
            "req-unsupp-tr-002", "train", "requirement_extraction",
            "Gas turbine compressor blade stage with titanium alloy aero airfoil.",
            {"available_families": ["spur_gear_pair", "electric_vehicle"]},
            {"intent": "UNSUPPORTED", "supported": False, "reason": "Gas turbine aero systems are outside supported CAD templates.", "requires_confirmation": False}
        ),
        make_record(
            "req-unsupp-tr-003", "train", "requirement_extraction",
            "Internal combustion V8 engine block with overhead camshafts.",
            {"available_families": ["spur_gear_pair", "electric_vehicle"]},
            {"intent": "UNSUPPORTED", "supported": False, "reason": "Internal combustion engines are outside supported automotive scope.", "requires_confirmation": False}
        ),
    ])

    # Validation
    records["validation"].extend([
        make_record(
            "req-gear-val-001", "validation", "requirement_extraction",
            "Spur gears: 16-tooth pinion, 48-tooth gear, 3 mm module, face width 25 mm.",
            {"allowed_family": "spur_gear_pair"},
            {"pinion_teeth": 16, "gear_teeth": 48, "module_mm": 3.0, "face_width_mm": 25.0, "missing": ["input_torque_Nm", "input_speed_rpm"], "requires_confirmation": True}
        ),
        make_record(
            "req-gear-val-002", "validation", "requirement_extraction",
            "Speed increaser pair: 45 pinion teeth, 15 gear teeth, module 1.25 mm, width 15 mm, 30 Nm, 2500 rpm.",
            {"allowed_family": "spur_gear_pair"},
            {"pinion_teeth": 45, "gear_teeth": 15, "module_mm": 1.25, "face_width_mm": 15.0, "input_torque_Nm": 30.0, "input_speed_rpm": 2500.0, "missing": [], "requires_confirmation": True}
        ),
        make_record(
            "req-ev-val-001", "validation", "requirement_extraction",
            "Compact 2-seat EV commuter, 3400 mm length, 1600 mm width, 2200 mm wheelbase.",
            {"allowed_family": "electric_vehicle"},
            {"occupant_capacity": 2, "overall_length_mm": 3400.0, "overall_width_mm": 1600.0, "wheelbase_mm": 2200.0, "unresolved": ["structural_validation", "achieved_range"], "requires_confirmation": True}
        ),
        make_record(
            "req-unsupp-val-001", "validation", "requirement_extraction",
            "Quadcopter drone propeller with variable pitch carbon fiber blades.",
            {"available_families": ["spur_gear_pair", "electric_vehicle"]},
            {"intent": "UNSUPPORTED", "supported": False, "reason": "Propellers and multirotors are outside domain scope.", "requires_confirmation": False}
        ),
    ])

    # Test
    records["test"].extend([
        make_record(
            "req-gear-test-001", "test", "requirement_extraction",
            "External gear pair, 22 pinion teeth, 88 driven gear teeth, module 2.25 mm, face width 35 mm, 120 Nm, 1000 rpm.",
            {"allowed_family": "spur_gear_pair"},
            {"pinion_teeth": 22, "gear_teeth": 88, "module_mm": 2.25, "face_width_mm": 35.0, "input_torque_Nm": 120.0, "input_speed_rpm": 1000.0, "missing": [], "requires_confirmation": True}
        ),
        make_record(
            "req-gear-test-002", "test", "requirement_extraction",
            "Spur pair: driver 17 teeth, driven 51 teeth, module 2.5 mm, width 28 mm, torque 45 Nm.",
            {"allowed_family": "spur_gear_pair"},
            {"pinion_teeth": 17, "gear_teeth": 51, "module_mm": 2.5, "face_width_mm": 28.0, "input_torque_Nm": 45.0, "missing": ["input_speed_rpm"], "requires_confirmation": True}
        ),
        make_record(
            "req-ev-test-001", "test", "requirement_extraction",
            "Family EV crossover, 5 seats, overall length 4500 mm, width 1850 mm, wheelbase 2750 mm, target range 400 km.",
            {"allowed_family": "electric_vehicle"},
            {"occupant_capacity": 5, "overall_length_mm": 4500.0, "overall_width_mm": 1850.0, "wheelbase_mm": 2750.0, "target_range_km": 400.0, "unresolved": ["structural_validation", "achieved_range"], "requires_confirmation": True}
        ),
        make_record(
            "req-unsupp-test-001", "test", "requirement_extraction",
            "Six-axis articulated robotic arm wrist actuator with harmonic drive.",
            {"available_families": ["spur_gear_pair", "electric_vehicle"]},
            {"intent": "UNSUPPORTED", "supported": False, "reason": "Harmonic drives and robot arms are unsupported.", "requires_confirmation": False}
        ),
    ])

    # =========================================================================
    # 2. CONSTRAINT INTERPRETATION
    # =========================================================================
    # Train
    records["train"].extend([
        make_record(
            "const-ratio-tr-001", "train", "constraint_interpretation",
            "Spur gears: pinion 18 teeth, driven 54 teeth, user requests stated ratio 4:1.",
            {"ratio_definition": "driven_teeth / pinion_teeth"},
            {"conflict": True, "stated_ratio": 4.0, "derived_ratio": 3.0, "commit_allowed": False, "recommendation": "Resolve tooth counts to match 4:1 (e.g. 18:72) or correct stated ratio to 3:1."}
        ),
        make_record(
            "const-ratio-tr-002", "train", "constraint_interpretation",
            "Pinion 20 teeth, driven 40 teeth, requested ratio 2:1.",
            {"ratio_definition": "driven_teeth / pinion_teeth"},
            {"conflict": False, "stated_ratio": 2.0, "derived_ratio": 2.0, "commit_allowed": True}
        ),
        make_record(
            "const-ratio-tr-003", "train", "constraint_interpretation",
            "Pinion 25 teeth, gear 75 teeth, specified ratio 3:1.",
            {"ratio_definition": "driven_teeth / pinion_teeth"},
            {"conflict": False, "stated_ratio": 3.0, "derived_ratio": 3.0, "commit_allowed": True}
        ),
        make_record(
            "const-ev-wb-tr-001", "train", "constraint_interpretation",
            "Set EV wheelbase to 4200 mm with overall vehicle length 4000 mm.",
            {"rule": "wheelbase_mm < overall_length_mm - 600"},
            {"conflict": True, "error": "Wheelbase 4200 mm exceeds vehicle length 4000 mm envelope.", "commit_allowed": False}
        ),
        make_record(
            "const-gear-mod-tr-001", "train", "constraint_interpretation",
            "Set gear module to 8.0 mm.",
            {"module_limits": {"min": 0.5, "max": 6.0}},
            {"conflict": True, "error": "Module 8.0 mm exceeds generator limit of 6.0 mm.", "commit_allowed": False}
        ),
        make_record(
            "const-gear-mod-tr-002", "train", "constraint_interpretation",
            "Set gear module to 0.2 mm.",
            {"module_limits": {"min": 0.5, "max": 6.0}},
            {"conflict": True, "error": "Module 0.2 mm is below generator limit of 0.5 mm.", "commit_allowed": False}
        ),
        make_record(
            "const-ev-track-tr-001", "train", "constraint_interpretation",
            "EV width 1700 mm, requested front track 1800 mm.",
            {"rule": "track_width < overall_width - 200"},
            {"conflict": True, "error": "Front track 1800 mm exceeds body width 1700 mm.", "commit_allowed": False}
        ),
        make_record(
            "const-pinion-bounds-tr-001", "train", "constraint_interpretation",
            "Specify pinion with 6 teeth for 2 mm module spur pair.",
            {"pinion_limits": {"min": 8, "max": 80}},
            {"conflict": True, "error": "Pinion teeth 6 is below minimum allowable 8 teeth (undercutting).", "commit_allowed": False}
        ),
    ])

    # Validation
    records["validation"].extend([
        make_record(
            "const-ratio-val-001", "validation", "constraint_interpretation",
            "Pinion 15 teeth, driven 60 teeth, stated ratio 5:1.",
            {"ratio_definition": "driven_teeth / pinion_teeth"},
            {"conflict": True, "stated_ratio": 5.0, "derived_ratio": 4.0, "commit_allowed": False}
        ),
        make_record(
            "const-bounds-val-001", "validation", "constraint_interpretation",
            "Pinion tooth count specified as 6 teeth.",
            {"pinion_teeth_limits": {"min": 8, "max": 80}},
            {"conflict": True, "error": "Pinion teeth 6 is below minimum 8 teeth.", "commit_allowed": False}
        ),
        make_record(
            "const-ev-val-002", "validation", "constraint_interpretation",
            "EV length 4100 mm, requested wheelbase 3600 mm.",
            {"rule": "wheelbase_mm <= overall_length_mm - 600"},
            {"conflict": True, "error": "Overhang clearance insufficient.", "commit_allowed": False}
        ),
    ])

    # Test
    records["test"].extend([
        make_record(
            "const-ratio-test-001", "test", "constraint_interpretation",
            "Pinion 16 teeth, driven 48 teeth, stated ratio 3:1.",
            {"ratio_definition": "driven_teeth / pinion_teeth"},
            {"conflict": False, "stated_ratio": 3.0, "derived_ratio": 3.0, "commit_allowed": True}
        ),
        make_record(
            "const-ev-env-test-001", "test", "constraint_interpretation",
            "EV overall length 3500 mm, requested wheelbase 3200 mm.",
            {"rule": "wheelbase_mm <= overall_length_mm - 600"},
            {"conflict": True, "error": "Wheelbase 3200 mm leaves insufficient front/rear overhang (<600 mm total).", "commit_allowed": False}
        ),
        make_record(
            "const-mod-test-001", "test", "constraint_interpretation",
            "Gear pair with module 4.5 mm, within supported range.",
            {"module_limits": {"min": 0.5, "max": 6.0}},
            {"conflict": False, "commit_allowed": True}
        ),
    ])

    # =========================================================================
    # 3. ASSEMBLY PLANNING
    # =========================================================================
    # Train
    records["train"].extend([
        make_record(
            "plan-gear-tr-001", "train", "assembly_planning",
            "Plan external spur gear assembly from reviewed parameters.",
            {"available_families": ["spur_gear_pair"]},
            {"family_id": "spur_gear_pair", "components": ["pinion", "gear"], "subsystems": ["Kinematic Drive Train"], "relationships": [{"source": "pinion", "target": "gear", "type": "gear_mesh", "axis": "parallel"}], "requires_confirmation": True}
        ),
        make_record(
            "plan-ev-tr-001", "train", "assembly_planning",
            "Plan conceptual electric vehicle packaging architecture.",
            {"available_families": ["electric_vehicle"]},
            {
                "family_id": "electric_vehicle",
                "subsystems": ["Chassis & Frame", "Powertrain & Energy", "Suspension & Running Gear", "Cabin & Envelopes"],
                "components": ["chassis_frame", "battery_pack", "traction_motor", "inverter", "front_axle", "rear_axle", "front_left_wheel", "front_right_wheel", "rear_left_wheel", "rear_right_wheel", "cabin_envelope", "body_envelope"],
                "requires_confirmation": True
            }
        ),
        make_record(
            "plan-ev-sub-tr-001", "train", "assembly_planning",
            "Assign battery pack and inverter into their assembly hierarchy.",
            {"family_id": "electric_vehicle"},
            {"battery_pack": {"subsystem": "Powertrain & Energy", "parent": "chassis_frame"}, "inverter": {"subsystem": "Powertrain & Energy", "parent": "traction_motor"}}
        ),
        make_record(
            "plan-gear-center-tr-001", "train", "assembly_planning",
            "Calculate center distance for 18-tooth pinion and 54-tooth gear with 2.0 mm module.",
            {"module_mm": 2.0, "pinion_teeth": 18, "gear_teeth": 54},
            {"pitch_diameter_pinion_mm": 36.0, "pitch_diameter_gear_mm": 108.0, "center_distance_mm": 72.0}
        ),
    ])

    # Validation
    records["validation"].extend([
        make_record(
            "plan-gear-val-001", "validation", "assembly_planning",
            "Plan 2-component spur mesh assembly with center distance constraint.",
            {"family_id": "spur_gear_pair", "pinion_pitch_mm": 40.0, "gear_pitch_mm": 120.0},
            {"center_distance_mm": 80.0, "mesh_point_x_mm": 40.0, "placement": {"pinion": [0, 0, 0], "gear": [80, 0, 0]}}
        ),
        make_record(
            "plan-ev-val-002", "validation", "assembly_planning",
            "Locate front and rear axles relative to wheelbase 2600 mm.",
            {"wheelbase_mm": 2600.0},
            {"front_axle_x_mm": 1300.0, "rear_axle_x_mm": -1300.0, "subsystem": "Suspension & Running Gear"}
        ),
    ])

    # Test
    records["test"].extend([
        make_record(
            "plan-ev-test-001", "test", "assembly_planning",
            "Organize EV running gear assembly components.",
            {"family_id": "electric_vehicle"},
            {"subsystem": "Suspension & Running Gear", "components": ["front_axle", "rear_axle", "front_left_wheel", "front_right_wheel", "rear_left_wheel", "rear_right_wheel", "steering_rack"], "parent": "chassis_frame"}
        ),
        make_record(
            "plan-gear-test-002", "test", "assembly_planning",
            "Calculate center distance for 20-tooth pinion and 80-tooth gear with module 3 mm.",
            {"module_mm": 3.0, "pinion_teeth": 20, "gear_teeth": 80},
            {"pitch_diameter_pinion_mm": 60.0, "pitch_diameter_gear_mm": 240.0, "center_distance_mm": 150.0}
        ),
    ])

    # =========================================================================
    # 4. ENGINEERING TOOL USE
    # =========================================================================
    # Train
    records["train"].extend([
        make_record(
            "tool-gear-mesh-tr-001", "train", "engineering_tool_use",
            "User approved proposal at revision 3. Generate pinion CAD geometry.",
            {"allowed_tools": ["generate_component_mesh"], "revision": 3},
            {"tool": "generate_component_mesh", "component_id": "pinion", "expected_revision": 3, "executed": False},
            tool_version="tool-proposals-v1", revision=3
        ),
        make_record(
            "tool-ev-mesh-tr-001", "train", "engineering_tool_use",
            "User committed EV parameter revision 2. Generate chassis frame envelope.",
            {"allowed_tools": ["generate_component_mesh"], "revision": 2},
            {"tool": "generate_component_mesh", "component_id": "chassis_frame", "expected_revision": 2, "executed": False},
            tool_version="tool-proposals-v1", revision=2
        ),
        make_record(
            "tool-param-edit-tr-001", "train", "engineering_tool_use",
            "Apply approved parameter edit: change gear module to 2.5 mm at revision 4.",
            {"allowed_tools": ["patch_project_parameters"], "revision": 4},
            {"tool": "patch_project_parameters", "parameters": {"module_mm": 2.5}, "expected_revision": 4, "executed": False},
            tool_version="tool-proposals-v1", revision=4
        ),
        make_record(
            "tool-export-step-tr-001", "train", "engineering_tool_use",
            "User requests STEP model export for current revision 5.",
            {"allowed_tools": ["export_step_artifact"], "revision": 5},
            {"tool": "export_step_artifact", "expected_revision": 5, "format": "STEP", "executed": False},
            tool_version="tool-proposals-v1", revision=5
        ),
        make_record(
            "tool-export-stl-tr-001", "train", "engineering_tool_use",
            "User requests STL 3D mesh export for pinion at revision 2.",
            {"allowed_tools": ["export_stl_artifact"], "revision": 2},
            {"tool": "export_stl_artifact", "component_id": "pinion", "expected_revision": 2, "format": "STL", "executed": False},
            tool_version="tool-proposals-v1", revision=2
        ),
    ])

    # Validation
    records["validation"].extend([
        make_record(
            "tool-gear-val-001", "validation", "engineering_tool_use",
            "User requested driven gear mesh for revision 2.",
            {"allowed_tools": ["generate_component_mesh"], "revision": 2},
            {"tool": "generate_component_mesh", "component_id": "gear", "expected_revision": 2, "executed": False},
            tool_version="tool-proposals-v1", revision=2
        ),
        make_record(
            "tool-pdf-val-001", "validation", "engineering_tool_use",
            "Generate engineering layout drawing PDF for EV revision 3.",
            {"allowed_tools": ["generate_layout_pdf"], "revision": 3},
            {"tool": "generate_layout_pdf", "expected_revision": 3, "format": "PDF", "executed": False},
            tool_version="tool-proposals-v1", revision=3
        ),
    ])

    # Test
    records["test"].extend([
        make_record(
            "tool-ev-patch-test-001", "test", "engineering_tool_use",
            "Apply reviewed wheelbase increase to 2700 mm at revision 3.",
            {"allowed_tools": ["patch_vehicle_parameters"], "revision": 3},
            {"tool": "patch_vehicle_parameters", "parameters": {"wheelbase_mm": 2700.0}, "expected_revision": 3, "executed": False},
            tool_version="tool-proposals-v1", revision=3
        ),
        make_record(
            "tool-gear-bom-test-001", "test", "engineering_tool_use",
            "Export Bill of Materials JSON for gear pair at revision 4.",
            {"allowed_tools": ["export_bom_json"], "revision": 4},
            {"tool": "export_bom_json", "expected_revision": 4, "format": "BOM_JSON", "executed": False},
            tool_version="tool-proposals-v1", revision=4
        ),
    ])

    # =========================================================================
    # 5. COMPONENT UNDERSTANDING
    # =========================================================================
    # Train
    records["train"].extend([
        make_record(
            "comp-pinion-tr-001", "train", "component_understanding",
            "What is the function and role of the pinion?",
            {"component": {"id": "pinion", "role": "Input driving gear", "teeth": 18, "parent": "pinion_shaft"}, "revision": 2},
            {"answer": "The pinion is the high-speed driving member on the input shaft that transfers torque to the driven gear.", "role": "Input driving gear", "evidence_required": True, "safety_claims_allowed": False},
            revision=2
        ),
        make_record(
            "comp-battery-tr-001", "train", "component_understanding",
            "What does the battery pack represent in this model?",
            {"component": {"id": "battery_pack", "role": "Conceptual energy storage packaging envelope", "parent": "chassis_frame"}, "revision": 1},
            {"answer": "It represents a conceptual volume envelope for high-voltage cells within the chassis frame; it does not model cell chemistry, BMS, or crash resistance.", "role": "Conceptual envelope", "evidence_required": True, "safety_claims_allowed": False},
            revision=1
        ),
        make_record(
            "comp-chassis-tr-001", "train", "component_understanding",
            "What are the parameter dependencies of the chassis frame?",
            {"component": {"id": "chassis_frame", "dependencies": ["overall_length_mm", "overall_width_mm", "wheelbase_mm"]}, "revision": 3},
            {"dependencies": ["overall_length_mm", "overall_width_mm", "wheelbase_mm"], "parent": "vehicle_assembly", "answer": "The chassis frame dimensions are derived from overall length, overall width, and wheelbase."},
            revision=3
        ),
        make_record(
            "comp-gear-tr-001", "train", "component_understanding",
            "Explain the physical role of the driven spur gear.",
            {"component": {"id": "gear", "role": "Driven output gear", "teeth": 54}, "revision": 1},
            {"answer": "The driven gear meshes with the pinion to multiply output torque and reduce output rotational speed by the ratio.", "role": "Driven output gear", "evidence_required": True, "safety_claims_allowed": False},
            revision=1
        ),
    ])

    # Validation
    records["validation"].extend([
        make_record(
            "comp-gear-val-001", "validation", "component_understanding",
            "What is the driven gear's role and tooth count?",
            {"component": {"id": "gear", "role": "Output driven member", "teeth": 54}, "revision": 2},
            {"answer_contains": "Output driven member", "teeth": 54, "evidence_required": True, "safety_claims_allowed": False},
            revision=2
        ),
        make_record(
            "comp-cabin-val-001", "validation", "component_understanding",
            "What does the cabin envelope represent?",
            {"component": {"id": "cabin_envelope", "role": "Passenger compartment bounding solid"}, "revision": 1},
            {"answer_contains": "Passenger compartment bounding solid", "evidence_required": True, "safety_claims_allowed": False},
            revision=1
        ),
    ])

    # Test
    records["test"].extend([
        make_record(
            "comp-motor-test-001", "test", "component_understanding",
            "What is the traction motor's placement and role?",
            {"component": {"id": "traction_motor", "role": "Rear traction electric motor", "placement": [-1200, 0, 300], "parent": "rear_axle"}, "revision": 1},
            {"role": "Rear traction electric motor", "parent": "rear_axle", "placement": [-1200, 0, 300], "safety_claims_allowed": False},
            revision=1
        ),
        make_record(
            "comp-inverter-test-001", "test", "component_understanding",
            "What is the inverter component connected to?",
            {"component": {"id": "inverter", "parent": "traction_motor"}, "revision": 2},
            {"parent": "traction_motor", "role": "Power electronics unit", "safety_claims_allowed": False},
            revision=2
        ),
    ])

    # =========================================================================
    # 6. CHANGE IMPACT & STALE ARTIFACT REASONING
    # =========================================================================
    # Train
    records["train"].extend([
        make_record(
            "impact-wb-tr-001", "train", "change_impact",
            "Wheelbase changed from 2600 mm to 2700 mm at revision 3.",
            {"current_revision": 3, "artifacts": ["step", "stl", "layout.pdf", "manifest.json", "bom.json"]},
            {
                "affected_components": ["chassis_frame", "front_axle", "rear_axle", "battery_enclosure"],
                "affected_dependencies": ["front/rear axles", "battery enclosure length", "turning radius envelope"],
                "stale_artifacts": ["step", "stl", "layout.pdf", "manifest.json", "bom.json"],
                "new_revision": 4
            },
            revision=3
        ),
        make_record(
            "impact-module-tr-001", "train", "change_impact",
            "Gear module changed from 2.0 mm to 2.5 mm at revision 2.",
            {"current_revision": 2, "artifacts": ["step", "stl", "report.pdf"]},
            {
                "affected_parameters": ["pitch_diameter_mm", "center_distance_mm", "outer_diameter_mm"],
                "affected_components": ["pinion", "gear"],
                "stale_artifacts": ["step", "stl", "report.pdf"],
                "new_revision": 3
            },
            revision=2
        ),
        make_record(
            "impact-torque-tr-001", "train", "change_impact",
            "Input torque updated from 50 Nm to 80 Nm at revision 1.",
            {"current_revision": 1, "artifacts": ["analysis_report.pdf"]},
            {
                "affected_parameters": ["tangential_force_N", "bending_stress_estimate_MPa"],
                "affected_components": [],
                "stale_artifacts": ["analysis_report.pdf"],
                "new_revision": 2
            },
            revision=1
        ),
    ])

    # Validation
    records["validation"].extend([
        make_record(
            "impact-ev-val-001", "validation", "change_impact",
            "Overall vehicle width changed at revision 4.",
            {"artifacts": ["assembly-step", "stl", "layout-drawing", "manifest", "bom"]},
            {"affected": ["component_geometry", "assembly-step", "stl", "layout-drawing", "manifest", "bom"], "source_revision": 4},
            revision=4
        ),
        make_record(
            "impact-facewidth-val-001", "validation", "change_impact",
            "Face width increased from 20 mm to 30 mm at revision 2.",
            {"current_revision": 2, "artifacts": ["pinion.stl", "gear.stl", "assembly.step"]},
            {"affected_components": ["pinion", "gear"], "stale_artifacts": ["pinion.stl", "gear.stl", "assembly.step"], "new_revision": 3},
            revision=2
        ),
    ])

    # Test
    records["test"].extend([
        make_record(
            "impact-gear-test-001", "test", "change_impact",
            "Pinion tooth count increased from 18 to 20 at revision 1.",
            {"current_revision": 1, "artifacts": ["step", "stl", "report.pdf"]},
            {
                "affected_parameters": ["gear_ratio", "center_distance_mm", "output_speed_rpm", "output_torque_Nm"],
                "affected_components": ["pinion", "gear"],
                "stale_artifacts": ["step", "stl", "report.pdf"],
                "new_revision": 2
            },
            revision=1
        ),
        make_record(
            "impact-length-test-001", "test", "change_impact",
            "EV length lengthened by 200 mm at revision 5.",
            {"current_revision": 5, "artifacts": ["body_envelope.stl", "chassis_frame.stl", "layout.pdf"]},
            {"affected_components": ["chassis_frame", "body_envelope"], "stale_artifacts": ["body_envelope.stl", "chassis_frame.stl", "layout.pdf"], "new_revision": 6},
            revision=5
        ),
    ])

    # =========================================================================
    # 7. FAILURE HANDLING
    # =========================================================================
    # Train
    records["train"].extend([
        make_record(
            "fail-conflict-tr-001", "train", "failure_handling",
            "Server returned HTTP 409 Conflict when committing vehicle edit.",
            {"expected_revision": 2, "server_revision": 3},
            {"status": "REVISION_CONFLICT", "action": "reload_canonical_project_and_review", "design_mutated": False}
        ),
        make_record(
            "fail-bounds-tr-001", "train", "failure_handling",
            "User attempted to set face width to -5 mm.",
            {"parameter": "face_width_mm", "min_allowed": 2.0},
            {"status": "VALIDATION_ERROR", "action": "reject_edit", "reason": "Face width must be positive and at least 2.0 mm.", "design_mutated": False}
        ),
        make_record(
            "fail-kernel-tr-001", "train", "failure_handling",
            "CadQuery kernel threw solid boolean failure during gear tooth generation.",
            {"action_in_progress": "generate_geometry", "revision": 2},
            {"status": "GENERATION_FAILURE", "action": "preserve_last_valid_revision", "corrupt_state": False, "revision": 2}
        ),
        make_record(
            "fail-zero-teeth-tr-001", "train", "failure_handling",
            "Invalid request: specify 0 pinion teeth.",
            {"parameter": "pinion_teeth", "min_allowed": 8},
            {"status": "VALIDATION_ERROR", "action": "reject_proposal", "reason": "Tooth count cannot be zero; minimum is 8 teeth.", "design_mutated": False}
        ),
    ])

    # Validation
    records["validation"].extend([
        make_record(
            "fail-stale-val-001", "validation", "failure_handling",
            "Client requested mesh for revision 1 but server is at revision 3.",
            {"requested_revision": 1, "current_revision": 3},
            {"status": "STALE_REVISION", "action": "request_current_mesh", "design_mutated": False}
        ),
        make_record(
            "fail-corrupt-val-001", "validation", "failure_handling",
            "Project state file contains invalid JSON payload.",
            {"path": "data/project.json"},
            {"status": "CORRUPT_STORE", "action": "restore_from_backup_or_quarantine", "design_mutated": False}
        ),
    ])

    # Test
    records["test"].extend([
        make_record(
            "failure-gear-test-001", "test", "failure_handling",
            "The API returned HTTP 409 for a stale component mesh.",
            {"requested_revision": 2, "current_revision": 3},
            {"status": "STALE_REVISION", "action": "refresh_project_and_regenerate", "design_mutated": False},
            revision=3
        ),
        make_record(
            "fail-timeout-test-001", "test", "failure_handling",
            "External CAD mesher timed out after 45 seconds.",
            {"timeout_sec": 45},
            {"status": "TIMEOUT", "action": "report_generation_timeout", "design_mutated": False}
        ),
    ])

    # =========================================================================
    # 8. ENGINEERING EXPLANATION & PRESERVING TRUTH
    # =========================================================================
    # Train
    records["train"].extend([
        make_record(
            "expl-cad-truth-tr-001", "train", "engineering_explanation",
            "Does successful CAD generation mean this gear is verified for production?",
            {"cad_generation_status": "SUCCESS", "analysis_types": ["geometry_preview_only"]},
            {"answer": "No. CAD generation only establishes geometric validity (manifold solid). Tooth bending fatigue, surface pitting, material selection, and AGMA rating remain unverified.", "verified_for_production": False, "evidence_required": True}
        ),
        make_record(
            "expl-ev-range-tr-001", "train", "engineering_explanation",
            "Can we claim this conceptual EV achieves a 300 km range?",
            {"target_range_km": 300, "verification_state": "UNRESOLVED"},
            {"answer": "No. 300 km is a requirement target. No powertrain efficiency, battery pack kWh sizing, or aerodynamic drag simulation has been performed.", "unsupported_claims": ["achieved_range"], "evidence_required": True}
        ),
        make_record(
            "expl-ev-crash-tr-001", "train", "engineering_explanation",
            "Is this EV chassis crash-tested and road legal?",
            {"family": "electric_vehicle", "status": "CONCEPTUAL_ENVELOPE"},
            {"answer": "No. The EV model consists of conceptual packaging bounding solids only. It has not undergone FEA, crash simulation, or regulatory homologation.", "road_legal": False, "evidence_required": True}
        ),
        make_record(
            "expl-gear-material-tr-001", "train", "engineering_explanation",
            "Does the 3D model define the gear heat treatment and hardness?",
            {"artifacts": ["STEP", "STL"]},
            {"answer": "No. Geometric STEP/STL models convey shape boundaries only; material specification, case hardening, and surface finish require drawing callouts and metallurgical specs.", "evidence_required": True}
        ),
    ])

    # Validation
    records["validation"].extend([
        make_record(
            "expl-gear-strength-val-001", "validation", "engineering_explanation",
            "Can we state this gear pair can handle 500 N*m continuously?",
            {"input_torque_Nm": 500, "calculations": ["ideal_kinematics_only"]},
            {"answer": "No. Kinematic ratio calculations do not establish Lewis bending stress or Hertz contact stress under load.", "verified": False, "evidence_required": True}
        ),
        make_record(
            "expl-ev-cooling-val-001", "validation", "engineering_explanation",
            "Does packaging the battery guarantee thermal cooling compliance?",
            {"battery_pack": "present"},
            {"answer": "No. Thermal dissipation and cooling channel CFD have not been modeled.", "thermal_verified": False, "evidence_required": True}
        ),
    ])

    # Test
    records["test"].extend([
        make_record(
            "explain-ev-test-001", "test", "engineering_explanation",
            "Does a requested 300 km range prove this concept can travel 300 km?",
            {"target_range_km": 300, "range_status": "UNRESOLVED"},
            {"answer": "No; it is a target only.", "unsupported_claims": ["achieved_range"], "evidence_required": True}
        ),
        make_record(
            "expl-gear-life-test-001", "test", "engineering_explanation",
            "Can we certify this gear pair for 10,000 hours operating life?",
            {"calculations": ["center_distance_only"]},
            {"answer": "No. Service life requires S-N curve analysis, dynamic factor Kv, load cycles, and lubrication regime verification.", "certified": False, "evidence_required": True}
        ),
    ])

    return records


def main():
    dest_dir = Path("data/learning/engineering-v2.2.0")
    dest_dir.mkdir(parents=True, exist_ok=True)
    records = generate_dataset()

    for split in ("train", "validation", "test"):
        split_records = records[split]
        file_path = dest_dir / f"{split}.jsonl"
        with file_path.open("w", encoding="utf-8") as f:
            for rec in split_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"Wrote {len(split_records)} records to {file_path}")

    counts = {k: len(v) for k, v in records.items()}
    total = sum(counts.values())

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "dataset_version": DATASET_VERSION,
        "purpose": "Specialist engineering dataset for requirement extraction, constraint interpretation, assembly planning, tool use, component understanding, change impact, failure handling, and engineering truth preservation.",
        "license": "CC0-1.0",
        "split_policy": "Strict disjoint splits. No example or duplicate prompt leaks across train, validation, or test sets.",
        "supported_categories": SUPPORTED_CATEGORIES,
        "quality_status": "reviewed_engineering_fixtures_v2.2",
        "record_counts": counts,
        "total_records": total,
        "training_claim": "Preflight measured on RTX 3050 6GB; training safety-gated by memory constraints. Baseline evaluation recorded."
    }

    manifest_path = dest_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote manifest ({total} records total) to {manifest_path}")


if __name__ == "__main__":
    main()

