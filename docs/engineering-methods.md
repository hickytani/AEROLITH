# Engineering methods and limitations

## Supported calculations

Inputs are millimetres, newton-metres, and revolutions per minute. API input fields are numeric and state their units; arbitrary unit-bearing values are not accepted. Requirement text extraction explicitly converts torque stated in N·mm to N·m. The external gear ratio is `z_driven / z_pinion`; pitch diameter is `module × tooth_count`; center distance is half the sum of pitch diameters. Under an explicitly stated ideal, lossless transmission assumption, output speed is input speed divided by ratio and output torque is input torque multiplied by ratio. These are algebraic kinematics and ideal torque relations, not a tooth-strength result.

The CAD boundary places four vertices per tooth using an educational trapezoidal tip approximation between a root radius of `module × (teeth − 2.5) / 2` and tip radius of `module × (teeth + 2) / 2`. CadQuery builds an Open CASCADE extruded polygon solid with a center bore and assembles the two components at pitch-center distance. The reported `outer_diameter_mm` is the conventional nominal addendum-circle diameter `module × (teeth + 2)`, not the axis-aligned bounding-box size of the phase-dependent polygon. The illustrative shared bore is `min(max(2 × module, 4 mm), 0.7 × minimum root diameter)` and is an explicit unverified assumption, not a shaft interface requirement. STEP preserves the kernel assembly; STL tessellates it. This is genuine CAD-kernel geometry with an approximate tooth profile, not an involute gear design. Valid solids and visual placement do not establish correct tooth meshing or engagement.

## Status and evidence

The API `verification` object gives each analysis a state, summary, and evidence. Supported states are `PASSED`, `WARNING`, `FAILED`, `PARTIAL`, `UNKNOWN`, `UNTESTED`, `UNOBSERVABLE`, and `EXECUTION_ERROR`. The top-level `overall` result is `PARTIAL` for any valid design and never `PASSED`; failed implemented input checks make it `FAILED`, without asserting mechanical failure. Implemented input checks may pass without implying physical performance. Ideal kinematics are `PARTIAL`; polygonal geometry is `WARNING`; tooth strength/contact are `UNKNOWN`; thermal analysis is `UNTESTED`; service conditions are `UNOBSERVABLE`. API execution failures carry `EXECUTION_ERROR`. No result is a simulation, safety factor, certification, or manufacturing assessment. Reports include the revision and report version. Project calculation records contain formula, substitution, units, assumptions, reference note, method version and the source revision.

## Validation

The server enforces integer tooth-count ranges (pinion 8–80, gear 8–120), module 0.5–6 mm, face width 2–60 mm, and finite positive torque/speed. Ratio is derived from tooth counts on edits; malformed, empty, non-finite, or out-of-range edits are rejected. Full candidate projects are validated before persistence.

## Numerical reference checks

`docs/engineering-reference-validation.md` records public references, assumptions, fixed reference values, and tolerances. API regression cases cover equal and non-divisible ratios and supported input boundaries through persisted state. CAD tests inspect vertex rings, through-bores and bounding dimensions, and reopen STEP/STL exports with Open CASCADE. These are implementation regression checks; they are not an independent standards benchmark or evidence of gear strength, contact, fatigue life, tooth engagement, manufacturing suitability, or safety.

The component preview uses CAD-generated STL coordinates in millimetres with one Three.js scene unit per millimetre. Component endpoints bind the response to the generating component and revision, identify STL/mm, and return the artifact SHA-256. The UI verifies the digest and finite triangle data before adding a mesh. Camera FIT uses the union of visible mesh bounds. Mesh validity and placement do not validate physical contact; the gears remain the polygonal educational approximation described above.

## Known gaps

No involute construction, pressure angle, backlash, profile shift, interference/contact-ratio checks, shaft or support design, material properties, standards-based bending/contact stress, fatigue, thermal behavior, solver, uncertainty, or independent benchmark is included. Do not use these artifacts for manufacture or real-world design decisions.
