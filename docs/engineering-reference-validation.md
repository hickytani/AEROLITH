# Engineering reference validation

## Scope

This note records public references and calculations behind the educational external spur-pair outputs. They support standard reference geometry and the involute/base-circle construction, not tooth-contact or strength validation.

## References

1. KHK Gears, [Calculation of Gear Dimensions](https://khkgears.net/gear-knowledge/gear-technical-reference/calculation-gear-dimensions/), section 4.1 and Table 4.1. The page defines the ordinary standard external spur gear case (no profile shift), with reference diameter `d = mz`, addendum `m`, whole depth `2.25m`, tip diameter `d_a = d + 2m`, and root diameter `d_f = d − 2.5m`. Its worked example gives 12/24 teeth at module 3 mm, pitch diameters 36/72 mm and center distance 54 mm. Assumptions: ordinary unshifted standard full-depth teeth; this is a reference geometry convention, not a statement about this application's tooth profile.
2. KHK Gears, [Spur Gears Technical Information (catalog PDF)](https://khkgears.net/pdf/2023/spur-gears.pdf), page 5, center-distance relation `a = m(Z1 + Z2)/2` and symbol definitions. It corroborates the external pair center-distance equation.
3. KHK Gears, [Root Clearance](https://khkgears.net/new/gear_knowledge/gear-nomenclature/root-clearance.html). The nomenclature states addendum `1.00m`, dedendum `1.25m`, and resulting clearance `0.25m`; this is consistent with the standard root diameter `d − 2.5m`.
4. OpenStax, [Work and Power for Rotational Motion](https://openstax.org/books/university-physics-volume-1/pages/10-8-work-and-power-for-rotational-motion), equation `P = τω`.
5. NIST, [SI Units of Length](https://www.nist.gov/pml/owm/si-units-length), for the exact millimetre-to-metre scale used in the `N·mm` to `N·m` conversion.
6. MIT, [Gears: Involutes](https://pergatory.mit.edu/resources/FUNdaMENTALs%20Book%20pdf/FUNdaMENTALs%20Topic%206.PDF), for the involute base-circle construction and the dependence of compatible involute gearing on pressure angle.
7. NASA, [Analytical and Experimental Evaluation of Spur Gear Tooth Root Stresses](https://ntrs.nasa.gov/api/citations/20130000783/downloads/20130000783.pdf?attachment=true), for spur-gear base-circle and pressure-angle relations. This is a reference for geometry, not evidence that this application implements the report's stress analysis.
8. Budynas, R. G. and Nisbett, J. K., *Shigley's Mechanical Engineering Design*, 11th Edition, McGraw-Hill, Chapter 14 (Gears: Mechanical Aspects), Table 14-2 (Values of the Lewis Form Factor Y for 20° Full-Depth Involute Teeth) and equation 14-7 (`σ = W_t / (F m Y)` in metric SI units). Reference for the Lewis bending stress calculation and form factor table.

## Equations and stated assumptions

For an ordinary external pair with pinion tooth count `z1`, driven tooth count `z2`, and common module `m`:

- Pitch diameter: `d = mz` (KHK reference 1).
- Ratio: `i = z2/z1`. This follows for an external pair from equal tangential velocities at the touching reference circles, `ω1(d1/2) = ω2(d2/2)`, and `d = mz`. Rotation directions are opposite; the API reports speed magnitude.
- Center distance: `a = (d1+d2)/2 = m(z1+z2)/2` (KHK references 1 and 2).
- Ideal speed magnitude: `n2 = n1/i`, from the same equal-tangential-velocity relationship.
- Ideal torque magnitude: `T2 = T1 i`, assuming equal input/output power with zero losses (`P = τω`, OpenStax reference 4). This is not a predicted real output torque or rating.
- Standard nominal addendum and root reference diameters: `d_a = m(z+2)` and `d_f = m(z−2.5)` (KHK references 1 and 3).
- Involute base diameter: `d_b = d cos α`, where `α` is the reference pressure angle (MIT and NASA references 6 and 7). The CAD flank is interpolated from 17 exact samples of the circle involute parameterization `x = r_b(cos t + t sin t)`, `y = r_b(sin t − t cos t)`. For the ordinary unshifted assumption, pitch-circle half tooth thickness is `π/(2z)`.
- Torque conversion: `1 N·mm = 0.001 N·m` because `1 mm = 0.001 m` (NIST reference 5).
- Tangential transmitted load at pitch circle: `F_t = 2000 · T1 / d1` (N, with input torque `T1` in N·m and pinion pitch diameter `d1` in mm).
- Lewis bending stress: `σ_b = F_t / (b · m · Y)` (MPa, with face width `b` in mm, module `m` in mm, and dimensionless form factor `Y` interpolated from Shigley Table 14-2 for 20° full-depth teeth, scaled by `tan(α)/tan(20°)` if `α ≠ 20°`). Assumptions: single-tooth tip load, dynamic factor `K_v = 1.0`, application factor `K_a = 1.0`, no stress concentration factor, and no material allowable comparison. This is a simplified educational estimate, not an AGMA or ISO gear rating.

The CAD generator interpolates one spline edge through 17 exact samples (16 intervals) per involute flank, uses addendum `m` and dedendum `1.25m`, and connects each active flank start to the root circle with a straight radial connector. That connector is not a cutter-generated trochoid. The geometry assumes no profile shift and zero nominal backlash. The nominal addendum diameter need not equal the axis-aligned CAD bounds because the sampled tooth profile is phase-dependent. Actual spline edges are sampled and checked against the polar involute relation; this verifies implementation geometry only. Nominal center distance does not prove contact or interference-free operation.

## Fixed reference cases

The following expected values are literal test fixtures independently evaluated from the equations above, not outputs generated by calling the implementation under test.

| z1/z2 | m (mm) | n1 (rpm) | T1 (N·m) | Ratio | d1/d2 (mm) | a (mm) | n2 (rpm) | ideal T2 (N·m) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 18/54 | 2 | 900 | 8 | 3 | 36/108 | 72 | 300 | 24 |
| 17/53 | 1.1 | 1000 | 5.3 | 3.1176470588235294 | 18.7/58.3 | 38.5 | 320.7547169811321 | 16.523529411764706 |
| 16/16 | 1 | 1200 | 2 | 1 | 16/16 | 16 | 1200 | 2 |
| 8/8 | 0.5 | 120 | 0.5 | 1 | 4/4 | 4 | 120 | 0.5 |
| 80/120 | 6 | 1200 | 4 | 1.5 | 480/720 | 600 | 800 | 6 |

### Lewis bending stress reference case

For the default spur gear pair (`z1 = 18`, `z2 = 54`, `m = 2.0 mm`, `b = 12.0 mm`, `α = 20°`, `T1 = 8.0 N·m`):

| Quantity | Formula / Source | Independent Reference Value |
|---|---|---:|
| Pinion pitch diameter `d1` | `m · z1` | `36.0 mm` |
| Tangential transmitted load `F_t` | `2000 · T1 / d1` | `444.444 N` (`4000/9 N`) |
| Pinion Lewis form factor `Y1` | Shigley Table 14-2 (`z = 18`) | `0.3090` |
| Gear Lewis form factor `Y2` | Linear interpolation between `z=50` (0.409) and `z=60` (0.422) for `z=54` | `0.4142` |
| Pinion Lewis bending stress `σ_b1` | `F_t / (b · m · Y1)` = `444.444 / (12 · 2 · 0.3090)` | `59.925 MPa` (approx. `59.9 MPa`) |
| Gear Lewis bending stress `σ_b2` | `F_t / (b · m · Y2)` = `444.444 / (12 · 2 · 0.4142)` | `44.708 MPa` (approx. `44.7 MPa`) |

The unit test `test_lewis_bending_stress_reference_calculation` validates these exact figures against `derive(default_design())` and confirms that pinion bending stress exceeds gear bending stress because `Y1 < Y2`.

The API reference-case tests compare floats with absolute tolerance `1e−10` and zero relative tolerance, then check the persisted revision and inputs. The geometric arithmetic has exact simple products; the tolerance is for IEEE-754 serialization and division. The existing standalone engineering-reference tests also check range boundaries and conversion parsing.

For the default 18-tooth pinion, module 2 mm, the nominal addendum diameter is 40 mm. With the documented tooth phase, maximum-radius vertices are at 5 degrees from the X/Y axes; the analytical axis span is `2 × 20 × cos(5°) = 39.8477879237 mm`. The kernel test checks this span and the expected two root and two tip vertices per tooth, with `1e−7 mm` tolerance for trigonometric and kernel floating-point noise. STEP is reopened into two valid solids and its volume is compared to the source assembly. STL is reopened as a tessellated shape; the `0.2 mm` XY bounding tolerance allows deviation from the source STEP bounds under the configured `0.08 mm` linear tessellation tolerance. These checks establish file readability and geometric consistency at the tested model settings, not physical gear correctness.

The default pinion's analytic base radius is independently fixed at `9 × cos(20°) = 16.9144671741465 mm`; its root and addendum radii are `15.5 mm` and `20 mm`. The assembly geometry regression asserts those literal references against measured Open CASCADE profile radii and additionally injects a 12-tooth CAD solid into the accepted 18-tooth pinion position to prove the profile check fails. Actual spline edge samples are tested against the polar involute equation with a `1e−6 rad` angular residual limit. These are geometry implementation checks; they are not an independent gear contact/profile certification.

## Verification status meaning

`overall` is `PARTIAL` when implemented input consistency checks pass, and `FAILED` when they fail. It is deliberately never `PASSED`: strength, contact, thermal behavior, and service conditions are unresolved or untested. The failed input state means an implemented constraint was violated; it is not a finding of mechanical failure. Individual results retain their own evidence and scope.

## Generated assembly geometry checks (Milestone 4)

The `assembly_verification` object is a software/geometry consistency record, not an additional physical design standard. Check definitions are versioned as `assembly-relationships-0.1` and each row records the project revision and geometry revision it inspected.

For gear assemblies, the generated CadQuery child transforms are compared with `a = m(z1 + z2)/2` at a `0.05 mm` translation tolerance. Both solid Z bounds are compared with accepted face width at `0.01 mm`. Actual solid vertices are checked for root/tip radii and profile-start location; sampled flank angles are independently compared with the polar involute equation at `1e-6 rad` residual. Base circles are recomputed from accepted `m`, `z` and pressure angle. The check also records solid validity/positive volume and the generator's display phase. The ratio check remains `PARTIAL`; tooth contact remains `UNOBSERVABLE`. These criteria test generated geometry consistency, not conjugate pair engagement, interference-free operation, strength, or manufacturing fitness.

For EV assemblies, tire/rim/hub bbox centers, tire/axle references, rail symmetry, overall outer bounds, and crossmember locations are measured from actual generated CadQuery solids with `0.05 mm` location/dimension tolerance. Each modeled crossmember is Boolean-intersected with both rails; a positive OCCT overlap volume demonstrates intersection only. This model has no joint, restraint, fastener, mount datum, or clearance acceptance criteria, so package/frame mounting stays `UNOBSERVABLE` and overall assembly status remains `PARTIAL`. The checks provide no vehicle structural, dynamic, thermal, range, crash, safety, regulatory, or roadworthiness validation.
