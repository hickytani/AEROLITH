from aeropkmech.domain import Component, Design, Requirements
from aeropkmech.drawings import GEAR_DRAWING_VERSION, gear_pair_reference_pdf


def test_gear_reference_pdf_is_a_single_landscape_revision_sheet():
    design = Design(
        revision=7,
        requirements=Requirements(
            gear_ratio=3,
            input_torque_Nm=8,
            input_speed_rpm=900,
            module_mm=2,
            face_width_mm=12,
        ),
        assumptions=["Bore is illustrative only."],
        components=[
            Component(id="pinion", name="Pinion", teeth=18),
            Component(id="gear", name="Driven gear", teeth=54),
        ],
        status={},
    )

    pdf = gear_pair_reference_pdf(design)
    assert pdf.startswith(b"%PDF-")
    assert b"/MediaBox [ 0 0 792 612 ]" in pdf
    assert b"/Count 1" in pdf
    assert GEAR_DRAWING_VERSION.encode("ascii") in pdf
    assert b"NOT FOR MANUFACTURE" in pdf
    assert b"REFERENCE ONLY." in pdf
    assert b"pitch-center reference" in pdf
    assert b"module_mm=demo-gearbox:module_mm" in pdf
    assert b"pinion_teeth=demo-gearbox:pinion_teeth" in pdf
    assert b"/Subject" in pdf
    assert b'"source_revision":7' in pdf
    assert len(pdf) > 1500
