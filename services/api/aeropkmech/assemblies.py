"""Typed assembly relationships checked against generated CAD snapshots."""
from __future__ import annotations

import math
import hashlib
from typing import Any, Literal
from functools import lru_cache

import cadquery as cq
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .automotive import (
    COMPONENT_INFO,
    VEHICLE_COMPONENT_PARAMETER_DEPENDENCIES,
    VehicleDesign,
    vehicle_component_solids,
)
from .domain import Design
from .engineering import derive
from .verification import VerificationState

ASSEMBLY_CHECK_VERSION = "assembly-relationships-0.1"


class AssemblyComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    parent_id: str
    parameter_refs: list[str]
    placement: dict[str, Any]
    bounds_mm: tuple[float, float, float]
    geometry_valid: bool
    volume_mm3: float


class AssemblyRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: Literal[
        "nominal-pitch-center-placement", "common-axial-width", "parallel-coaxial-axes", "sampled-involute-profile", "tooth-contact",
        "concentric-packaging-stack", "mirrored-frame-rails", "crossmember-rail-geometric-overlap",
        "wheel-axle-reference-placement", "axle-reference-placement", "component-completeness-and-solid-validity",
        "packaging-association", "declared-envelope-containment",
    ]
    component_ids: list[str]
    parameter_refs: list[str]
    description: str
    verification_state: VerificationState


class AssemblyHierarchyNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    parent_id: str | None = None
    kind: Literal["assembly", "subsystem", "component"]


class AssemblyCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    version: str = ASSEMBLY_CHECK_VERSION
    revision: int = 0
    geometry_revision: int = 0
    relationship_id: str | None = None
    component_ids: list[str] = Field(default_factory=list)
    parameter_refs: list[str] = Field(default_factory=list)
    state: VerificationState
    rule: str
    expected: dict[str, Any] = Field(default_factory=dict)
    observed: dict[str, Any] = Field(default_factory=dict)
    units: str | None = None
    tolerance: float | None = None
    evidence: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class AssemblyEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    family_id: str
    family_schema_version: str
    assembly_id: str
    revision: int
    geometry_revision: int
    generator_version: str
    check_version: str = ASSEMBLY_CHECK_VERSION
    units: str = "mm"
    source_prompt: str | None = None
    source_prompt_sha256: str | None = None
    requirements: dict[str, Any] = Field(default_factory=dict)
    overall_state: VerificationState
    hierarchy: list[AssemblyHierarchyNode]
    components: list[AssemblyComponent]
    relationships: list[AssemblyRelationship]
    checks: list[AssemblyCheck]
    limitations: list[str]

    @model_validator(mode="after")
    def validate_references_and_revision(self):
        component_ids = [item.id for item in self.components]
        if len(set(component_ids)) != len(component_ids):
            raise ValueError("Assembly component IDs must be unique.")
        component_set = set(component_ids)
        hierarchy_by_id = {item.id:item for item in self.hierarchy}
        if len(hierarchy_by_id) != len(self.hierarchy) or self.assembly_id not in hierarchy_by_id or hierarchy_by_id[self.assembly_id].kind != "assembly":
            raise ValueError("Assembly hierarchy must contain one stable root assembly ID and unique nodes.")
        for node in self.hierarchy:
            if node.parent_id is not None and node.parent_id not in hierarchy_by_id:
                raise ValueError(f"Assembly hierarchy node {node.id} references a missing parent.")
            if node.id != self.assembly_id and node.parent_id is None:
                raise ValueError("Only the root assembly may omit a parent ID.")
            visited = {node.id}
            parent_id = node.parent_id
            while parent_id is not None:
                if parent_id in visited:
                    raise ValueError("Assembly hierarchy cannot contain cycles.")
                visited.add(parent_id)
                parent_id = hierarchy_by_id[parent_id].parent_id
        if any(hierarchy_by_id.get(item.id) is None or hierarchy_by_id[item.id].kind != "component" or hierarchy_by_id[item.id].parent_id != item.parent_id for item in self.components):
            raise ValueError("Assembly component parent references must match the typed hierarchy.")
        known_parameters = set().union(*(set(item.parameter_refs) for item in self.components))
        relationship_ids = [item.id for item in self.relationships]
        if len(set(relationship_ids)) != len(relationship_ids):
            raise ValueError("Assembly relationship IDs must be unique.")
        relationship_set = set(relationship_ids)
        for relationship in self.relationships:
            if not relationship.component_ids or not set(relationship.component_ids) <= component_set:
                raise ValueError(f"Assembly relationship {relationship.id} references missing components.")
            if not set(relationship.parameter_refs) <= known_parameters:
                raise ValueError(f"Assembly relationship {relationship.id} references unknown parameters.")
        for check in self.checks:
            if check.relationship_id is not None and check.relationship_id not in relationship_set:
                raise ValueError(f"Assembly check {check.id} references a missing relationship.")
            if not set(check.component_ids) <= component_set:
                raise ValueError(f"Assembly check {check.id} references missing components.")
            if not set(check.parameter_refs) <= known_parameters:
                raise ValueError(f"Assembly check {check.id} references unknown parameters.")
            if check.revision not in (0, self.revision) or check.geometry_revision not in (0, self.geometry_revision):
                raise ValueError("Assembly checks must use the enclosing design and geometry revisions.")
            check.revision = self.revision
            check.geometry_revision = self.geometry_revision
        if self.geometry_revision != self.revision:
            raise ValueError("Assembly evidence must be generated from the same revision as the design snapshot.")
        if self.source_prompt is not None:
            expected_hash = hashlib.sha256(self.source_prompt.encode("utf-8")).hexdigest()
            if self.source_prompt_sha256 != expected_hash:
                raise ValueError("Assembly source prompt hash does not match its bytes.")
        elif self.source_prompt_sha256 is not None:
            raise ValueError("Assembly source prompt hash cannot exist without source text.")
        for name, trace in self.requirements.items():
            evidence = trace.get("evidence")
            span = trace.get("source_span")
            if span is not None:
                if not evidence or not self.source_prompt or evidence not in self.source_prompt:
                    raise ValueError(f"Assembly requirement source span for {name} is not supported by the source prompt.")
                start, end = span.get("start"), span.get("end")
                if not isinstance(start,int) or not isinstance(end,int) or start < 0 or end < start or self.source_prompt is None or self.source_prompt[start:end] != span.get("text"):
                    raise ValueError(f"Assembly requirement source span for {name} is invalid.")
        if self.requirements:
            for component in self.components:
                if not set(component.parameter_refs) <= set(self.requirements):
                    raise ValueError(f"Assembly component {component.id} references an unknown requirement.")
            for relationship in self.relationships:
                if not set(relationship.parameter_refs) <= set(self.requirements):
                    raise ValueError(f"Assembly relationship {relationship.id} references an unknown requirement.")
            for check in self.checks:
                if not set(check.parameter_refs) <= set(self.requirements):
                    raise ValueError(f"Assembly check {check.id} references an unknown requirement.")
        if self.overall_state == VerificationState.PASSED and any(item.state != VerificationState.PASSED for item in self.checks):
            raise ValueError("An assembly cannot be PASSED when a required check is incomplete or failed.")
        return self


def _bbox(shape: cq.Workplane) -> tuple[float, float, float, float, float, float]:
    box = shape.val().BoundingBox()
    return box.xmin, box.ymin, box.zmin, box.xmax, box.ymax, box.zmax


def _dims(shape: cq.Workplane) -> tuple[float, float, float]:
    bounds = _bbox(shape)
    return bounds[3] - bounds[0], bounds[4] - bounds[1], bounds[5] - bounds[2]


def _center(shape: cq.Workplane) -> tuple[float, float, float]:
    bounds = _bbox(shape)
    return tuple((bounds[i] + bounds[i + 3]) / 2 for i in range(3))


def _gear_assembly(design: Design) -> AssemblyEvidence:
    from .cad import GENERATOR_VERSION, build_assembly

    assembly = build_assembly(design)
    child_by_name = {child.name: child for child in assembly.children}
    ids = {"pinion": "pinion", "driven_gear": "gear"}
    component_rows: list[AssemblyComponent] = []
    for child_name, component_id in ids.items():
        child = child_by_name[child_name]
        translation, rotation = child.loc.toTuple()
        shape = child.obj
        component_rows.append(AssemblyComponent(
            id=component_id, parent_id="gear-pair",
            parameter_refs=["pinion_teeth" if component_id == "pinion" else "gear_teeth", "module_mm", "face_width_mm", "pressure_angle_deg"],
            placement={"kind":"assembly_transform","translation_mm":tuple(float(v) for v in translation),"rotation_euler_deg":tuple(float(v) for v in rotation)},
            bounds_mm=_dims(shape), geometry_valid=bool(shape.val().isValid()),
            volume_mm3=float(shape.val().Volume()),
        ))
    pinion = child_by_name["pinion"]
    gear = child_by_name["driven_gear"]
    p, g = design.components
    req = design.requirements
    derived = derive(design)
    expected_center = derived["center_distance_mm"]
    pinion_origin = tuple(float(v) for v in pinion.loc.toTuple()[0])
    gear_origin = tuple(float(v) for v in gear.loc.toTuple()[0])
    observed_center = math.dist(pinion_origin, gear_origin)
    expected_origin = (expected_center, 0.0, 0.0)
    center_ok = math.isclose(expected_center, observed_center, rel_tol=0, abs_tol=0.05) and all(math.isclose(a,b,rel_tol=0,abs_tol=0.05) for a,b in zip(gear_origin,expected_origin))
    width_expected = req.face_width_mm
    widths = {"pinion": _dims(pinion.obj)[2], "gear": _dims(gear.obj)[2]}
    widths_ok = all(math.isclose(value, width_expected, rel_tol=0, abs_tol=0.01) for value in widths.values()) and math.isclose(widths["pinion"], widths["gear"], rel_tol=0, abs_tol=0.01)
    t = gear.loc.toTuple()
    orientation_expected = 180 / g.teeth
    orientation_ok = abs(t[1][0]) <= 1e-6 and abs(t[1][1]) <= 1e-6 and math.isclose(t[1][2], orientation_expected, rel_tol=0, abs_tol=1e-6)
    axes_ok = all(math.isclose(value, 0, rel_tol=0, abs_tol=1e-6) for child in (pinion, gear) for value in child.loc.toTuple()[0][1:]) and all(abs(child.loc.toTuple()[1][0]) <= 1e-6 and abs(child.loc.toTuple()[1][1]) <= 1e-6 for child in (pinion, gear))
    solids_ok = all(row.geometry_valid and math.isfinite(row.volume_mm3) and row.volume_mm3 > 0 for row in component_rows)
    profile_measurements = {}
    profile_ok = True
    base_circle_measurements = {}
    base_circles_ok = True
    for child, component in ((pinion,p),(gear,g)):
        root = req.module_mm * (component.teeth - 2.5) / 2
        tip = req.module_mm * (component.teeth + 2) / 2
        pressure = math.radians(req.pressure_angle_deg)
        pitch_radius = req.module_mm * component.teeth / 2
        base_radius = pitch_radius * math.cos(pressure)
        flank_start = max(base_radius, root)
        values = [(vertex.Center().x, vertex.Center().y) for vertex in child.obj.val().Vertices()]
        radii = [math.hypot(x,y) for x,y in values]
        exterior_radii = [radius for radius in radii if radius > derived["bore_diameter_mm"] / 2 + 0.01]
        root_observed = min(exterior_radii)
        tip_observed = max(exterior_radii)
        start_vertices = [radius for radius in exterior_radii if math.isclose(radius, flank_start, rel_tol=0, abs_tol=1e-6)]
        pitch_angle = 2 * math.pi / component.teeth
        inv_pressure = math.tan(pressure) - pressure
        flank_residuals = []
        sampled_flank_edges = 0
        for edge in child.obj.val().Edges():
            edge_residuals = []
            for sample in range(1, 20):
                point = edge.positionAt(sample / 20)
                radius = math.hypot(point.x, point.y)
                if flank_start + 1e-4 < radius < tip - 0.01:
                    alpha = math.acos(min(1.0, base_radius / radius))
                    half_width = math.pi / (2 * component.teeth) + math.tan(alpha) - alpha - inv_pressure
                    angle = math.atan2(point.y, point.x) % pitch_angle
                    edge_residuals.append(min(abs(angle-half_width), abs(angle-(pitch_angle-half_width))))
            # Root/tip arcs and radial connectors do not have enough active
            # flank samples to count as an involute edge.
            if len(edge_residuals) >= 10:
                sampled_flank_edges += 1
                flank_residuals.extend(edge_residuals)
        max_flank_residual = max(flank_residuals, default=math.inf)
        matched = (
            math.isclose(root_observed, root, rel_tol=0, abs_tol=0.01)
            and math.isclose(tip_observed, tip, rel_tol=0, abs_tol=0.01)
            and len(start_vertices) >= 2 * component.teeth
            and sampled_flank_edges >= component.teeth * 4
            and len(flank_residuals) >= component.teeth * 4 * 15
            and max_flank_residual <= 1e-6
        )
        profile_ok &= matched
        base_circles_ok &= len(start_vertices) >= 2 * component.teeth
        profile_measurements[component.id]={"accepted_tooth_count":component.teeth,"expected_root_radius_mm":root,"observed_root_radius_mm":root_observed,"expected_tip_radius_mm":tip,"observed_tip_radius_mm":tip_observed,"sampled_involute_flank_edge_count":sampled_flank_edges,"sampled_involute_profile_points":len(flank_residuals),"maximum_involute_angular_residual_rad":max_flank_residual}
        base_circle_measurements[component.id]={"expected_base_radius_mm":base_radius,"observed_profile_start_radius_mm":min(start_vertices, default=None),"expected_profile_start_radius_mm":flank_start,"observed_profile_start_vertex_count":len(start_vertices)}
    ratio = g.teeth / p.teeth
    gear_values = {**design.requirements.model_dump(exclude_none=True), "pinion_teeth":p.teeth,"gear_teeth":g.teeth}
    gear_units = {
        "pinion_teeth": "teeth",
        "gear_teeth": "teeth",
        "gear_ratio": "ratio",
        "module_mm": "mm",
        "face_width_mm": "mm",
        "input_torque_Nm": "N·m",
        "input_speed_rpm": "rpm",
        "pressure_angle_deg": "deg",
        "hub_diameter_mm": "mm",
        "hub_length_mm": "mm",
        "bore_diameter_mm": "mm",
        "keyway_width_mm": "mm",
        "keyway_depth_mm": "mm",
    }
    requirements = {name:{"canonical_target":f"requirements.{name}" if name not in {"pinion_teeth","gear_teeth"} else f"components.{name.removesuffix('_teeth')}.teeth","value":value,"unit":gear_units.get(name, "mm"),"source":design.requirement_sources.get(name,"derived" if name=="gear_ratio" else "assumed"),"evidence":design.requirement_evidence.get(name)} for name,value in gear_values.items()}
    for trace in requirements.values():
        evidence = trace["evidence"]
        if evidence and design.source_prompt:
            start = design.source_prompt.find(evidence)
            if start >= 0:
                trace["source_span"] = {"start":start,"end":start+len(evidence),"text":evidence}
    return AssemblyEvidence(
        family_id=design.family, family_schema_version=design.schema_version,
        assembly_id="gear-pair", revision=design.revision, geometry_revision=design.revision,
        generator_version=GENERATOR_VERSION, source_prompt=design.source_prompt,
        source_prompt_sha256=hashlib.sha256(design.source_prompt.encode("utf-8")).hexdigest() if design.source_prompt else None,
        requirements=requirements, overall_state=VerificationState.PARTIAL,
        hierarchy=[AssemblyHierarchyNode(id="gear-pair",kind="assembly"),AssemblyHierarchyNode(id="pinion",parent_id="gear-pair",kind="component"),AssemblyHierarchyNode(id="gear",parent_id="gear-pair",kind="component")],
        components=component_rows,
        relationships=[
            AssemblyRelationship(id="gear-pair.center-distance", kind="nominal-pitch-center-placement", component_ids=["pinion", "gear"], parameter_refs=["pinion_teeth", "gear_teeth", "module_mm"], description="CAD component origins are placed at the nominal external-pair pitch-center distance.", verification_state=VerificationState.PASSED if center_ok else VerificationState.FAILED),
            AssemblyRelationship(id="gear-pair.common-face-width", kind="common-axial-width", component_ids=["pinion", "gear"], parameter_refs=["face_width_mm"], description="Both generated solids use the accepted shared face width.", verification_state=VerificationState.PASSED if widths_ok else VerificationState.FAILED),
            AssemblyRelationship(id="gear-pair.parallel-axes", kind="parallel-coaxial-axes", component_ids=["pinion", "gear"], parameter_refs=["module_mm", "pinion_teeth", "gear_teeth"], description="Both gear axes remain parallel to the assembly Z axis; centerline separation is in XY.", verification_state=VerificationState.PASSED if axes_ok else VerificationState.FAILED),
            AssemblyRelationship(id="gear-pair.profile-dimensions",kind="sampled-involute-profile",component_ids=["pinion","gear"],parameter_refs=["pinion_teeth","gear_teeth","module_mm","pressure_angle_deg"],description="Generated CAD flank vertices follow the sampled involute equation at the accepted pressure angle; addendum and dedendum radii match the documented assumptions.",verification_state=VerificationState.PASSED if profile_ok else VerificationState.FAILED),
            AssemblyRelationship(id="gear-pair.tooth-contact", kind="tooth-contact", component_ids=["pinion", "gear"], parameter_refs=["pinion_teeth", "gear_teeth", "module_mm", "pressure_angle_deg"], description="The actual profile is involute, but pair contact, interference and operating compatibility are not evaluated.", verification_state=VerificationState.UNOBSERVABLE),
        ],
        checks=[
            AssemblyCheck(id="gear.solids.valid", component_ids=["pinion", "gear"], parameter_refs=["pinion_teeth", "gear_teeth", "module_mm", "face_width_mm"], state=VerificationState.PASSED if solids_ok else VerificationState.FAILED, rule="Each generated Open CASCADE solid must be valid and have finite positive volume.", expected={"component_ids":["pinion","gear"],"volume_mm3":"finite and > 0"}, observed={row.id:{"valid":row.geometry_valid,"volume_mm3":row.volume_mm3,"bounds_mm":row.bounds_mm} for row in component_rows}, units="mm, mm^3", evidence=["Inspected the actual CadQuery assembly child solids produced for this revision."], limitations=["Solid validity does not establish functional meshing, load capacity, or manufacturing suitability."]),
            AssemblyCheck(id="gear.center-distance", relationship_id="gear-pair.center-distance", component_ids=["pinion", "gear"], parameter_refs=["pinion_teeth", "gear_teeth", "module_mm"], state=VerificationState.PASSED if center_ok else VerificationState.FAILED, rule="Driven-gear assembly origin equals (module * (z_pinion + z_gear) / 2, 0, 0); origin separation also equals that nominal distance.", expected={"distance_mm":expected_center,"gear_origin_mm":expected_origin}, observed={"distance_mm":observed_center,"pinion_origin_mm":pinion_origin,"gear_origin_mm":gear_origin}, units="mm", tolerance=0.05, evidence=[f"Derived from accepted values: {req.module_mm:g} * ({p.teeth} + {g.teeth}) / 2."], limitations=["Nominal reference-circle placement only; not a tooth-contact or interference check."]),
            AssemblyCheck(id="gear.face-width", relationship_id="gear-pair.common-face-width", component_ids=["pinion", "gear"], parameter_refs=["face_width_mm"], state=VerificationState.PASSED if widths_ok else VerificationState.FAILED, rule="Actual CAD solid Z bounds equal the accepted shared face width.", expected={"each_component_width_mm":width_expected}, observed={"pinion_width_mm":widths["pinion"],"gear_width_mm":widths["gear"]}, units="mm", tolerance=0.01, evidence=["Measured the generated CAD solid bounding dimensions."], limitations=["Equal face width does not prove axial alignment under real bearing/support constraints."]),
            AssemblyCheck(id="gear.axis-placement", relationship_id="gear-pair.parallel-axes", component_ids=["pinion", "gear"], parameter_refs=["pinion_teeth", "gear_teeth", "module_mm"], state=VerificationState.PASSED if axes_ok else VerificationState.FAILED, rule="Both actual assembly transforms preserve Z-parallel axes and zero Y/Z origin offsets.", expected={"axis":"+Z","origin_y_mm":0,"origin_z_mm":0,"gear_phase_deg":orientation_expected}, observed={"pinion_transform":pinion.loc.toTuple(),"gear_transform":gear.loc.toTuple()}, units="mm, deg", tolerance=1e-6, evidence=["Measured the generated CadQuery assembly child locations."], limitations=["The phase is a visualization convention, not validation of tooth engagement."]),
            AssemblyCheck(id="gear.profile-dimensions",relationship_id="gear-pair.profile-dimensions",component_ids=["pinion","gear"],parameter_refs=["pinion_teeth","gear_teeth","module_mm","pressure_angle_deg"],state=VerificationState.PASSED if profile_ok else VerificationState.FAILED,rule="Measured generated-solid root/tip/profile-start vertices and sampled spline edges against the polar involute flank equation; flank angular residual <= 1e-6 rad.",expected={component.id:{"root_radius_mm":req.module_mm*(component.teeth-2.5)/2,"tip_radius_mm":req.module_mm*(component.teeth+2)/2,"base_radius_mm":req.module_mm*component.teeth*math.cos(math.radians(req.pressure_angle_deg))/2,"flank_edge_count_including_end_faces":component.teeth*4} for component in (p,g)},observed=profile_measurements,units="mm, rad",tolerance=1e-6,evidence=["Independently sampled actual generated OCCT spline edges and measured CAD profile vertices."],limitations=["The flank spline interpolates discrete exact involute samples; the root connector is straight radial, not a cutter trochoid. This does not verify pair contact or interference."]),
            AssemblyCheck(id="gear.base-circles",component_ids=["pinion","gear"],parameter_refs=["pinion_teeth","gear_teeth","module_mm","pressure_angle_deg"],state=VerificationState.PASSED if base_circles_ok else VerificationState.FAILED,rule="Measured generated-solid vertices occur at the independently calculated max(base radius, root radius) involute start.",expected={key:{"base_radius_mm":req.module_mm*component.teeth*math.cos(math.radians(req.pressure_angle_deg))/2,"profile_start_radius_mm":max(req.module_mm*component.teeth*math.cos(math.radians(req.pressure_angle_deg))/2,req.module_mm*(component.teeth-2.5)/2)} for key,component in (("pinion",p),("gear",g))},observed=base_circle_measurements,units="mm",tolerance=1e-6,evidence=["Measured actual CAD vertex radii; independently calculated the base-circle and root radii from accepted inputs."],limitations=["Base-circle/profile-start agreement does not establish tooth contact or load capacity."]),
            AssemblyCheck(id="gear.ratio-derivation", component_ids=["pinion", "gear"], parameter_refs=["pinion_teeth", "gear_teeth"], state=VerificationState.PARTIAL, rule="Ideal external-pair ratio is derived as driven teeth / pinion teeth.", expected={"ratio":ratio}, observed={"ratio":derived["gear_ratio"],"source":"gear_teeth / pinion_teeth"}, units="ratio", evidence=[f"{g.teeth} / {p.teeth} = {ratio:g}; derivation follows canonical tooth counts."], limitations=["Ideal kinematic relation; pair contact and actual motion are not verified."]),
            AssemblyCheck(id="gear.tooth-contact", relationship_id="gear-pair.tooth-contact", component_ids=["pinion", "gear"], parameter_refs=["pinion_teeth", "gear_teeth", "module_mm", "pressure_angle_deg"], state=VerificationState.UNOBSERVABLE, rule="No validated contact ratio, tooth-pair interference or motion analysis is available.", expected={}, observed={}, units=None, tolerance=None, evidence=["The profile uses involute flanks, but no contact/interference solver is implemented."], limitations=["Do not interpret nominal center distance or visualization phase as proof of an operating mesh."]),
        ], limitations=["Sampled involute flanks with straight radial root connectors; no cutter trochoid, contact, interference, strength, fatigue, thermal, or manufacturing validation."],
    )


def _ev_assembly(design: VehicleDesign, solids: dict[str, cq.Workplane] | None = None) -> AssemblyEvidence:
    from .automotive import VEHICLE_GENERATOR_VERSION, VehicleParameters, vehicle_calculate, vehicle_requirement_trace

    generated = solids if solids is not None else vehicle_component_solids(design)
    calc = vehicle_calculate(design)
    component_rows: list[AssemblyComponent] = []
    for component_id, solid in generated.items():
        bbox = _bbox(solid)
        center = _center(solid)
        component_rows.append(AssemblyComponent(
            id=component_id, parent_id=COMPONENT_INFO[component_id][1],
            parameter_refs=list(VEHICLE_COMPONENT_PARAMETER_DEPENDENCIES.get(component_id, ())),
            placement={"kind":"measured_world_bounds","center_mm":center,"orientation":"baked into generated geometry; no separate component transform is exposed"}, bounds_mm=_dims(solid),
            geometry_valid=bool(solid.val().isValid()), volume_mm3=float(solid.val().Volume()),
        ))
    p = design.requirements
    tolerance = 0.05

    def same_center(ids: list[str]) -> tuple[bool, dict[str, tuple[float, float, float]], float]:
        centers = {cid: _center(generated[cid]) for cid in ids}
        max_delta = max((math.dist(centers[a], centers[b]) for i, a in enumerate(ids) for b in ids[i + 1:]), default=0.0)
        return max_delta <= tolerance, centers, max_delta

    relationships: list[AssemblyRelationship] = []
    checks: list[AssemblyCheck] = []
    for axle in ("front", "rear"):
        for side in ("left", "right"):
            wheel = f"{axle}-{side}"
            ids = [f"tire-{wheel}", f"rim-{wheel}", f"hub-{wheel}"]
            matched, centers, delta = same_center(ids)
            relation_id = f"ev.{wheel}.wheel-stack-concentric"
            refs = sorted(set().union(*(set(VEHICLE_COMPONENT_PARAMETER_DEPENDENCIES.get(cid, ())) for cid in ids)))
            relationships.append(AssemblyRelationship(id=relation_id,kind="concentric-packaging-stack",component_ids=ids,parameter_refs=refs,description="Tire, rim and hub envelope centers are coincident in the generated CAD layout; mechanical mounting is not modeled.",verification_state=VerificationState.PASSED if matched else VerificationState.FAILED))
            checks.append(AssemblyCheck(id=relation_id,relationship_id=relation_id,component_ids=ids,parameter_refs=refs,state=VerificationState.PASSED if matched else VerificationState.FAILED,rule="Euclidean distance between actual bounding-box centers of tire, rim and hub envelopes is at most 0.05 mm.",expected={"maximum_center_delta_mm":0.0},observed={"center_by_component_mm":centers,"maximum_center_delta_mm":delta},units="mm",tolerance=tolerance,evidence=["Centers measured from generated CadQuery solids."],limitations=["Coincident envelope centers do not establish bolt patterns, bearing fit, axle joints, or rotation clearance."]))

    rail_ids = ["frame-rail-left", "frame-rail-right"]
    rail_centers = {cid: _center(generated[cid]) for cid in rail_ids}
    rail_dims = {cid: _dims(generated[cid]) for cid in rail_ids}
    rails_equal = all(math.isclose(a,b,rel_tol=0,abs_tol=tolerance) for a,b in zip(rail_dims[rail_ids[0]],rail_dims[rail_ids[1]]))
    rail_mirror = rails_equal and all(math.isclose(rail_centers[rail_ids[0]][axis],rail_centers[rail_ids[1]][axis],rel_tol=0,abs_tol=tolerance) for axis in (0,2)) and math.isclose(rail_centers[rail_ids[0]][1],-rail_centers[rail_ids[1]][1],rel_tol=0,abs_tol=tolerance)
    relationships.append(AssemblyRelationship(id="ev.chassis.rail-pair-symmetry",kind="mirrored-frame-rails",component_ids=rail_ids,parameter_refs=["rear_track_mm","frame_rail_width_mm","frame_rail_height_mm","ground_clearance_mm"],description="Generated left/right rail envelopes have equal dimensions and mirrored Y placement.",verification_state=VerificationState.PASSED if rail_mirror else VerificationState.FAILED))
    checks.append(AssemblyCheck(id="ev.frame-rail-symmetry",relationship_id="ev.chassis.rail-pair-symmetry",component_ids=rail_ids,parameter_refs=["rear_track_mm","frame_rail_width_mm","frame_rail_height_mm","ground_clearance_mm"],state=VerificationState.PASSED if rail_mirror else VerificationState.FAILED,rule="Generated rail CAD dimensions match within 0.05 mm; X/Z centers match and Y centers are equal/opposite.",expected={"equal_bounds":True,"mirror_axis":"X-Z plane"},observed={"centers_mm":rail_centers,"bounds_mm":rail_dims},units="mm",tolerance=tolerance,evidence=["Measured the two generated rail CAD solids."],limitations=["Symmetric placement does not prove frame strength, joints, or load transfer."]))

    # Crossmembers are intentionally modeled as overlapping the rails. Inspect
    # actual OCCT intersection volume instead of treating manifest links as proof.
    rail_joint_ids = ["frame-rail-left", "frame-rail-right"]
    for crossmember_id, axle, sign in (("front-crossmember","front",1), ("rear-crossmember","rear",-1)):
        crossmember = generated[crossmember_id]
        expected_x = sign * (p.wheelbase_mm.value / 2) * 0.77
        center = _center(crossmember)
        position_ok = math.isclose(center[0], expected_x, rel_tol=0, abs_tol=tolerance) and math.isclose(center[1],0,rel_tol=0,abs_tol=tolerance)
        intersections = {}
        for rail_id in rail_joint_ids:
            volume = float(crossmember.val().intersect(generated[rail_id].val()).Volume())
            intersections[rail_id] = volume
        intersects_both = all(math.isfinite(value) and value > 0 for value in intersections.values())
        passed = position_ok and intersects_both
        relation_id = f"ev.chassis.{axle}-crossmember-rail-joints"
        ids = [crossmember_id, *rail_joint_ids]
        relationships.append(AssemblyRelationship(id=relation_id,kind="crossmember-rail-geometric-overlap",component_ids=ids,parameter_refs=["wheelbase_mm","frame_rail_width_mm","frame_rail_height_mm","rear_track_mm"],description="Crossmember is positioned at its defined wheelbase fraction and its generated solid overlaps both frame-rail solids.",verification_state=VerificationState.PASSED if passed else VerificationState.FAILED))
        checks.append(AssemblyCheck(id=relation_id,relationship_id=relation_id,component_ids=ids,parameter_refs=["wheelbase_mm","frame_rail_width_mm","frame_rail_height_mm","rear_track_mm"],state=VerificationState.PASSED if passed else VerificationState.FAILED,rule="Crossmember CAD bounding center matches X = +/-0.385 * wheelbase and Y = 0 within 0.05 mm; Open CASCADE intersection volume with each rail is positive.",expected={"center_x_mm":expected_x,"center_y_mm":0,"intersection_volume_mm3_each_rail":"> 0"},observed={"center_mm":center,"intersection_volume_mm3_by_rail":intersections},units="mm, mm^3",tolerance=tolerance,evidence=["Position and Boolean intersection volumes are measured from generated CAD solids."],limitations=["Solid overlap confirms geometric intersection only; it does not prove a designed joint, weld, fastener, strength, or load path."]))

    wheel_centers_expected = {item["id"]: (item["x_mm"], item["y_mm"], item["z_mm"]) for item in calc["wheel_centers"]}
    tire_ids = sorted(cid for cid in generated if cid.startswith("tire-"))
    tire_centers = {cid: _center(generated[cid]) for cid in tire_ids}
    wheel_position_ok = all(math.dist(tire_centers[f"tire-{wheel_id}"], expected) <= tolerance for wheel_id, expected in wheel_centers_expected.items())
    wheel_components = [*tire_ids,"front-axle-reference","rear-axle-reference"]
    wheel_relation_id = "ev.running-gear.wheel-and-axle-centers"
    relationships.append(AssemblyRelationship(id=wheel_relation_id,kind="wheel-axle-reference-placement",component_ids=wheel_components,parameter_refs=["wheelbase_mm","front_track_mm","rear_track_mm","tire_outer_diameter_mm"],description="Generated tire-envelope centers and axle-reference centers follow wheelbase, track and tire-radius coordinates.",verification_state=VerificationState.PASSED if wheel_position_ok else VerificationState.FAILED))
    checks.append(AssemblyCheck(id=wheel_relation_id,relationship_id=wheel_relation_id,component_ids=wheel_components,parameter_refs=["wheelbase_mm","front_track_mm","rear_track_mm","tire_outer_diameter_mm"],state=VerificationState.PASSED if wheel_position_ok else VerificationState.FAILED,rule="Tire CAD bounding-box center equals ( +/- wheelbase/2, +/- track/2, tire diameter/2 ) within 0.05 mm.",expected={wheel_id:coordinates for wheel_id,coordinates in wheel_centers_expected.items()},observed=tire_centers,units="mm",tolerance=tolerance,evidence=["Expected positions come from canonical wheelbase, track and tire diameter; observed centers come from generated tire solids."],limitations=["This is static envelope placement and does not validate steering, suspension motion, contact patch, or dynamic clearances."]))

    axle_ok = True
    axle_observed = {}
    for axle in ("front", "rear"):
        expected = (p.wheelbase_mm.value/2 if axle == "front" else -p.wheelbase_mm.value/2, 0.0, p.tire_outer_diameter_mm.value/2)
        actual = _center(generated[f"{axle}-axle-reference"])
        axle_observed[f"{axle}-axle-reference"] = actual
        axle_ok &= math.dist(actual, expected) <= tolerance
    axle_relation_id = "ev.running-gear.axle-reference-placement"
    axle_ids = ["front-axle-reference", "rear-axle-reference"]
    relationships.append(AssemblyRelationship(id=axle_relation_id,kind="axle-reference-placement",component_ids=axle_ids,parameter_refs=["wheelbase_mm","tire_outer_diameter_mm"],description="Generated axle reference centers are placed on vehicle centerline at wheelbase stations and tire-radius height.",verification_state=VerificationState.PASSED if axle_ok else VerificationState.FAILED))
    checks.append(AssemblyCheck(id=axle_relation_id,relationship_id=axle_relation_id,component_ids=axle_ids,parameter_refs=["wheelbase_mm","tire_outer_diameter_mm"],state=VerificationState.PASSED if axle_ok else VerificationState.FAILED,rule="Axle CAD bounding centers equal ( +/- wheelbase/2, 0, tire diameter/2 ) within 0.05 mm.",expected={"front":(p.wheelbase_mm.value/2,0,p.tire_outer_diameter_mm.value/2),"rear":(-p.wheelbase_mm.value/2,0,p.tire_outer_diameter_mm.value/2)},observed=axle_observed,units="mm",tolerance=tolerance,evidence=["Observed centers measured from the two generated axle-reference solids."],limitations=["Axle reference envelopes are not designed shafts or validated suspension interfaces."]))

    expected_ids = set(COMPONENT_INFO)
    all_valid = set(generated) == expected_ids and all(s.val().isValid() and math.isfinite(s.val().Volume()) and s.val().Volume() > 0 for s in generated.values())
    relationships.append(AssemblyRelationship(id="ev.assembly.component-integrity",kind="component-completeness-and-solid-validity",component_ids=sorted(expected_ids),parameter_refs=[],description="All required stable component IDs must map to valid positive-volume generated solids.",verification_state=VerificationState.PASSED if all_valid else VerificationState.FAILED))
    checks.append(AssemblyCheck(id="ev.component-solid-integrity",relationship_id="ev.assembly.component-integrity",component_ids=sorted(expected_ids),state=VerificationState.PASSED if all_valid else VerificationState.FAILED,rule="Expected component ID set equals generated CAD ID set; each Open CASCADE solid is valid with finite positive volume.",expected={"component_count":len(expected_ids),"component_ids":sorted(expected_ids)},observed={"component_count":len(generated),"component_ids":sorted(generated),"all_solids_valid":all_valid},units="mm, mm^3",tolerance=None,evidence=["Inspected all generated family component solids for this project revision."],limitations=["Geometry validity does not establish correct interfaces, performance, or vehicle safety."]))

    # Explicit associations to frame are packaging intent only: the existing model
    # has no mount faces, fasteners, restraint rules, or non-interference criteria.
    package_ids = ["battery-pack-envelope", "traction-motor-envelope", "inverter-envelope", "reduction-drive-envelope"]
    relationships.append(AssemblyRelationship(id="ev.propulsion.frame-packaging",kind="packaging-association",component_ids=[*package_ids,"frame-rail-left","frame-rail-right"],parameter_refs=sorted(set().union(*(set(VEHICLE_COMPONENT_PARAMETER_DEPENDENCIES.get(cid, ())) for cid in package_ids))),description="Propulsion envelopes are located relative to the chassis coordinate system, but mount/clearance constraints are not defined.",verification_state=VerificationState.PARTIAL))
    checks.append(AssemblyCheck(id="ev.propulsion-frame-interface",relationship_id="ev.propulsion.frame-packaging",component_ids=[*package_ids,"frame-rail-left","frame-rail-right"],parameter_refs=sorted(set().union(*(set(VEHICLE_COMPONENT_PARAMETER_DEPENDENCIES.get(cid, ())) for cid in package_ids))),state=VerificationState.UNOBSERVABLE,rule="Requires mounting datum, clearance and support constraints that are absent from this conceptual envelope model.",expected={},observed={"package_components_present":all(cid in generated for cid in package_ids)},units="mm",tolerance=None,evidence=["Stable package-envelope geometry exists in the generated assembly."],limitations=["Do not infer fit, clearance, thermal suitability, support, or electrical/mechanical integration."]))

    # Existing generator verifies envelope containment against actual assembly bounds.
    envelope = "body-envelope" in generated
    whole = calc["geometry_bounds_mm"]
    envelope_ok = whole["length"] <= p.overall_length_mm.value + tolerance and whole["width"] <= p.overall_width_mm.value + tolerance and whole["height"] <= p.body_height_mm.value + tolerance
    relationships.append(AssemblyRelationship(id="ev.assembly.declared-envelope",kind="declared-envelope-containment",component_ids=sorted(expected_ids),parameter_refs=["overall_length_mm","overall_width_mm","body_height_mm"],description="Union of generated component CAD bounds fits the declared overall length, width and body-height envelope.",verification_state=VerificationState.PASSED if envelope_ok else VerificationState.FAILED))
    checks.append(AssemblyCheck(id="ev.overall-envelope-containment",relationship_id="ev.assembly.declared-envelope",component_ids=sorted(expected_ids),parameter_refs=["overall_length_mm","overall_width_mm","body_height_mm"],state=VerificationState.PASSED if envelope_ok and envelope else VerificationState.FAILED,rule="Union of actual generated CAD bounding boxes does not exceed the three declared outer-envelope dimensions (0.05 mm tolerance).",expected={"length_mm":p.overall_length_mm.value,"width_mm":p.overall_width_mm.value,"height_mm":p.body_height_mm.value},observed=whole,units="mm",tolerance=tolerance,evidence=[f"Generated body envelope present: {envelope}.","Union bounds are computed from generated CAD solids."],limitations=["Outer-envelope containment does not validate occupant space, aerodynamic shape, range, performance, dynamics or roadworthiness."]))

    subsystem_ids=sorted({item.parent_id for item in component_rows})
    hierarchy=[AssemblyHierarchyNode(id="vehicle-assembly",kind="assembly"),*(AssemblyHierarchyNode(id=key,parent_id="vehicle-assembly",kind="subsystem") for key in subsystem_ids),*(AssemblyHierarchyNode(id=item.id,parent_id=item.parent_id,kind="component") for item in component_rows)]
    requirements={name:vehicle_requirement_trace(design,name) for name in VehicleParameters.model_fields if name not in {"occupant_source","occupant_evidence","propulsion_source","propulsion_evidence"}}
    return AssemblyEvidence(family_id=design.family,family_schema_version=design.schema_version,assembly_id="vehicle-assembly",revision=design.revision,geometry_revision=design.revision,generator_version=VEHICLE_GENERATOR_VERSION,source_prompt=design.source_prompt,source_prompt_sha256=hashlib.sha256(design.source_prompt.encode("utf-8")).hexdigest() if design.source_prompt else None,requirements=requirements,overall_state=VerificationState.PARTIAL,hierarchy=hierarchy,components=component_rows,relationships=relationships,checks=checks,limitations=["Concept packaging only. Physical joints, fit, interference, structural integrity, range, dynamics, thermal behavior, safety, crashworthiness, regulatory compliance and manufacturing readiness are not verified."])


def build_assembly_evidence(design: Design | VehicleDesign) -> dict[str, Any]:
    payload = design.model_dump_json()
    model = _cached_gear_assembly(payload) if design.family == "spur_gear_pair" else _cached_ev_assembly(payload)
    return model.model_dump(mode="json")


@lru_cache(maxsize=4)
def _cached_gear_assembly(payload: str) -> AssemblyEvidence:
    return _gear_assembly(Design.model_validate_json(payload))


@lru_cache(maxsize=4)
def _cached_ev_assembly(payload: str) -> AssemblyEvidence:
    return _ev_assembly(VehicleDesign.model_validate_json(payload))
