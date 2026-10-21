"""Revision-bound reference drawing for the supported educational gear pair."""
from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas

from .domain import Design
from .engineering import derive

GEAR_DRAWING_VERSION = "gear-reference-drawing-0.1"


def _arrow(c: canvas.Canvas, x: float, y: float, direction: int) -> None:
    c.line(x, y, x + direction * 5, y + 2)
    c.line(x, y, x + direction * 5, y - 2)


def _horizontal_dimension(c: canvas.Canvas, x1: float, x2: float, y: float, label: str) -> None:
    c.setStrokeColor(colors.HexColor("#536675"))
    c.setLineWidth(0.55)
    c.line(x1, y, x2, y)
    _arrow(c, x1, y, 1)
    _arrow(c, x2, y, -1)
    c.setFillColor(colors.HexColor("#243746"))
    c.setFont("Helvetica", 8)
    c.drawCentredString((x1 + x2) / 2, y + 4, label)


def gear_pair_reference_pdf(design: Design) -> bytes:
    """Create a two-view, dimensioned reference sheet, explicitly not a shop drawing."""
    d = derive(design)
    pinion, gear = design.components
    buffer = BytesIO()
    page_w, page_h = landscape(letter)
    c = canvas.Canvas(buffer, pagesize=(page_w, page_h), pageCompression=0)
    c.setTitle(f"{GEAR_DRAWING_VERSION} · Gear pair reference drawing {design.id} revision {design.revision}")
    c.setAuthor("AeroPKmech Studio")

    ink = colors.HexColor("#203443")
    muted = colors.HexColor("#536675")
    pitch_color = colors.HexColor("#23827d")
    c.setFillColor(ink)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(34, page_h - 36, "SPUR GEAR PAIR — REFERENCE LAYOUT")
    c.setFont("Helvetica", 8)
    c.setFillColor(muted)
    c.drawString(34, page_h - 51, f"Design {design.id} · revision {design.revision} · units: mm · drawing {GEAR_DRAWING_VERSION}")
    c.setFillColor(colors.HexColor("#8d291e"))
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(page_w - 34, page_h - 36, "NOT FOR MANUFACTURE")

    # Front view: circles are nominal references. The CAD tooth boundary is a
    # phased polygon approximation and intentionally is not represented as an involute.
    scale = 1.35
    center_y = 337.0
    left_x = 185.0
    right_x = left_x + d["center_distance_mm"] * scale
    c.setLineWidth(0.9)
    for center_x, component, od_key, pd_key in (
        (left_x, pinion, "pinion_outer_diameter_mm", "pinion_pitch_diameter_mm"),
        (right_x, gear, "gear_outer_diameter_mm", "gear_pitch_diameter_mm"),
    ):
        outer_r = d[od_key] * scale / 2
        pitch_r = d[pd_key] * scale / 2
        bore_r = d["bore_diameter_mm"] * scale / 2
        c.setStrokeColor(ink)
        c.circle(center_x, center_y, outer_r, stroke=1, fill=0)
        c.setStrokeColor(pitch_color)
        c.setDash(4, 3)
        c.circle(center_x, center_y, pitch_r, stroke=1, fill=0)
        c.setDash()
        c.setStrokeColor(muted)
        c.circle(center_x, center_y, bore_r, stroke=1, fill=0)
        c.setStrokeColor(muted)
        c.setLineWidth(0.45)
        c.line(center_x - 4, center_y, center_x + 4, center_y)
        c.line(center_x, center_y - 4, center_x, center_y + 4)
        c.setFillColor(ink)
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(center_x, center_y + outer_r + 12, component.name.upper())
        c.setFont("Helvetica", 7.5)
        c.setFillColor(muted)
        c.drawCentredString(center_x, center_y - outer_r - 12, f"z = {component.teeth} · d_p = {d[pd_key]:.2f} · d_a(ref) = {d[od_key]:.2f}")

    c.setStrokeColor(muted)
    c.setLineWidth(0.45)
    c.setDash(2, 2)
    c.line(left_x, center_y, right_x, center_y)
    c.setDash()
    _horizontal_dimension(c, left_x, right_x, 219, f"a = {d['center_distance_mm']:.2f} mm  (pitch-center reference)")
    c.setFillColor(ink)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(70, 190, "FRONT REFERENCE VIEW")
    c.setFont("Helvetica", 8)
    c.setFillColor(muted)
    c.drawString(70, 177, "Solid circle: nominal addendum reference · dashed: pitch circle · center: assumed bore")

    # Axial envelope view: the rectangles communicate specified face width only.
    c.setFillColor(ink)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(522, 448, "AXIAL ENVELOPE VIEW")
    c.setFillColor(muted)
    c.setFont("Helvetica", 8)
    c.drawString(522, 435, f"Specified face width b = {design.requirements.face_width_mm:.2f} mm")
    axial_scale = 2.0
    thickness = design.requirements.face_width_mm * axial_scale
    for index, (component, od_key) in enumerate(((pinion, "pinion_outer_diameter_mm"), (gear, "gear_outer_diameter_mm"))):
        x = 545 + index * 112
        height = d[od_key] * 0.72
        y = 325 - height / 2
        c.setStrokeColor(ink)
        c.setLineWidth(0.8)
        c.rect(x, y, thickness, height, stroke=1, fill=0)
        c.setFillColor(muted)
        c.setFont("Helvetica", 7.5)
        c.drawCentredString(x + thickness / 2, y - 13, component.name)
        c.drawCentredString(x + thickness / 2, y - 24, f"b = {design.requirements.face_width_mm:.2f} mm")
        c.drawCentredString(x + thickness / 2, y - 35, "envelope only")

    c.setStrokeColor(colors.HexColor("#b8c5cd"))
    c.line(34, 147, page_w - 34, 147)
    c.setFillColor(ink)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(34, 132, "DESIGN PARAMETERS")
    c.setFont("Helvetica", 8)
    c.setFillColor(muted)
    c.drawString(34, 117, f"Module m = {design.requirements.module_mm:.3f} mm   ·   Ratio i = {d['gear_ratio']:.5g}:1   ·   Bore = {d['bore_diameter_mm']:.2f} mm (illustrative assumption)")
    c.drawString(34, 103, f"Input speed = {design.requirements.input_speed_rpm:.2f} rpm   ·   Input torque = {design.requirements.input_torque_Nm:.3f} N·m   ·   geometry = cq-polygon-approx-0.1")
    c.setFillColor(colors.HexColor("#8d291e"))
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(34, 79, "EDUCATIONAL REFERENCE ONLY. CAD teeth are polygonal, not involute. This sheet does not establish engagement, clearances, strength, fit, tolerances, or manufacturing suitability.")
    c.setFillColor(muted)
    c.setFont("Helvetica", 7)
    c.drawRightString(page_w - 34, 42, f"Revision {design.revision} · all dimensions mm unless stated · page 1 of 1")
    c.showPage()
    c.save()
    return buffer.getvalue()
