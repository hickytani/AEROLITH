# Prompt-to-System Generation: Audit and Delivered Slice

**Review date:** 2026-10-20  
**Target prompt:** “Generate a two-seater sports car, electric powered, 4.2 m long, 1.8 m wide, with a 300 km range. Include the necessary mechanical and electrical systems.”

## Repository audit

The checkout uses Next.js 16 / React 19 / TypeScript for the web shell, Three.js for the Studio viewport, FastAPI / Pydantic for the API, CadQuery / Open CASCADE for the current CAD family, Pint for dimensional arithmetic, ReportLab for reports, and pytest plus Node tests. Those dependencies and their use are present in the repository.

The canonical project remains one locally persisted `spur_gear_pair@1.0`. It has two CAD-generated polygonal gear solids, deterministic ideal kinematics, revisioned state, SHA-256-indexed retained artifacts, HTML/PDF reports, and conservative verification summaries. The family is educational and does not implement involute teeth, strength, safety, or manufacturing validation. The artifact index tracks revision and content hash but does not yet have explicit dependency edges or automatic downstream regeneration.

Requirement extraction was deterministic and family-specific. The Studio contained an intake text area and button, but source inspection found no click handler for that control. P0 visibility, renderer lifecycle, viewport-height, and API-readiness fixes are present in the current Git history. The prior review recorded Chrome acceptance for the baseline gear flow.

There is no configured LLM, external provider, custom-model training pipeline, or vehicle engineering family. The existing synthetic JSONL evaluation harness is a deterministic parser evaluation baseline, not model-training data or independent engineering validation. Local persistence remains single-project and single-writer.

At audit start, the active branch was `codex/sprint-2-engineering-validation`, with `ee45d4e` also at `origin/main`. `apps/web/next-env.d.ts` had a pre-existing user edit. It remains unstaged and unchanged.

## Delivered architecture and behavior

`POST /api/v1/specifications/propose` accepts up to 4,000 characters and returns a Pydantic-validated version 1.0 proposal. The response includes domain, intent, system name, input values with units/source/evidence/status, a component/subsystem hierarchy with stable IDs and parent references, typed relationships, unresolved questions, conflicts, range issues, assumptions, limitations, available artifact types, and whether the proposal can be committed. This endpoint is read-only.

The Studio now wires its existing prompt intake to that endpoint. It renders the returned graph and source evidence using text nodes, exposes supported numeric parameters for review/editing, recalculates the gear ratio preview from reviewed tooth counts, updates unresolved fields, and requires an explicit commit action. Gear-pair commits use `PATCH /api/v1/project` with `expected_revision`; the API returns 409 if the canonical revision changed since review. Successful commits flow through the existing canonical persistence, calculations, geometry rebuild, and artifact status refresh.

The EV planner is a separate deterministic domain module, `automotive.py`. For the supplied prompt it extracts two occupants, 4,200 mm overall length, 1,800 mm overall width, 300 km target range, and electric propulsion. It proposes a top-level vehicle node, structural, running-gear, electric-propulsion, vehicle-support and sports-car performance-control groups, child roles, and conceptual interfaces such as battery-to-inverter and motor-to-reduction-drive. IDs and parent/interface links are validated in response schemas. The intake records simple unit conversions and declared input ranges.

All electric-vehicle nodes are marked `CONCEPTUAL_ONLY` with `generator_available: false`. There is no automotive family ID, no vehicle geometry generator, no CAD/drawing/BOM artifact, no mass or battery sizing, no performance calculation, and no commit action. Missing wheelbase, track, mass, speed, drive cycle, battery, thermal, and regulatory requirements remain explicit. This output is a conceptual architecture proposal; it is not a generated sports car or validated subsystem selection.

The fully supported output path at this audit's review point was the spur gear pair: a complete request could be reviewed and committed, after which real existing CadQuery geometry, ideal calculations, reports and exports were available at the new project revision. Gear extraction was deterministic and did not call an LLM.

### Later implementation update

The state above is a historical audit of the earlier prompt-only milestone. Subsequent EV and prompt-to-CAD milestones added `electric_vehicle@1.0`, a bounded 27-solid CadQuery packaging assembly, parameter-specific editing, and the component-to-requirement traceability described in section 24 of the current completion report. The vehicle remains a conceptual envelope model and does not provide the physical analyses listed as unsupported above.

## Changed files

- `services/api/aeropkmech/automotive.py`: narrow EV prompt extraction and conceptual subsystem/interface planner.
- `services/api/aeropkmech/intelligence.py`: versioned specification schema, provenance, range/conflict handling, gear-family plan, and EV dispatch.
- `services/api/aeropkmech/domain.py`, `main.py`: optional optimistic revision guard and the proposal route.
- `public/index.html`, `public/app.js`, `public/style.css`: functional Studio prompt intake, editable review fields, graph/limitations view, and explicit gear commit.
- `services/api/tests/`, `tests/frontend-contract.test.mjs`: proposal schema, extraction, revision race, and UI wiring coverage.
- `docs/api.md`, `docs/model-strategy.md`, `docs/feature-status.md`, `docs/roadmap.md`, `README.md`: API contract, scope and next implementation milestone.

## Capability status and next milestone

| Capability | Status | Boundary |
|---|---|---|
| Gear-pair prompt specification | Implemented; test verification recorded below | Deterministic typed values/evidence, review/edit, optimistic revision commit; one registered family only. |
| EV prompt values and subsystem graph | Conceptual; test verification recorded below | Narrow pattern extraction and rule-based graph only. No CAD generator, engineering analysis, or vehicle artifact. |
| CAD and calculations | Implemented for gear pair only | Polygonal CAD and ideal kinematics; not a vehicle generator or physical validation. |
| Artifact registry | Partial | Local retained files, revision/version/hash and stale marker; no dependency graph or job queue. |
| LLM/provider/key configuration | Unsupported | No provider calls, API-key configuration, training, or model lifecycle UI. |
| Vehicle 2D drawings, mass, range/power sizing and safety analysis | Unsupported | Requires vehicle component generators, engineering models and reference validation. |

The next coherent implementation is a bounded EV geometry family beginning with a dimensioned chassis envelope and wheel/tire primitives, then deterministic coordinate frames, an assembly manifest, and real revision-linked geometry artifacts. Do not claim the vehicle is generated until those artifacts and their relationships are tested in the browser against the canonical design revision.

## Verification

- `npm test`: **62 Python tests and 13 Node tests passed**, with one existing Starlette/httpx deprecation warning.
- `npm run build:web`: passed Next.js compilation, TypeScript, and static generation for `/`, `/designs/new`, `/learn`, and `/platform`.
- `npx tsc --noEmit --pretty false -p apps/web/tsconfig.json`: passed.
- `node --check` passed for `public/app.js`, `public/mesh-loader.js`, and `public/camera-fit.js`.
- `git diff --check`: passed.
- No new browser visual acceptance run was completed for the prompt-review experience. The checks above verify API, schema, revision guard, frontend contracts, and build behavior; visual review of prompt editing and the conceptual EV display remains outstanding.

No changes were committed or pushed for that milestone.

## Sprint 5: EV envelope generation vertical slice

The EV prompt now dispatches to `electric_vehicle@1.0`. Prompt-specified occupants, overall length/width, range and electric propulsion retain units, evidence and provenance. Missing packaging dimensions are configurable in the review form and marked `ASSUMED`; wheelbase, tracks, tire dimensions, body height, ground clearance and frame/body envelopes never masquerade as prompt input. A validated request is committed into the same `data/project.json` revision/history as the gear family with an optimistic revision check.

CadQuery produces 27 separate conceptual solids: four frame members, front/rear axle references, four each of tires/rims/hubs/suspension-link envelopes, a body envelope, and battery/motor/inverter/reduction-drive envelopes. Default wheel tracks and tire widths define the requested 1,800 mm vehicle width; the narrower body envelope leaves the four tire envelopes visible. Actual assembly bounds match the requested 4,200 × 1,800 mm outer envelope. The assembly manifest provides IDs, hierarchy, family, parent, bounding dimensions, centers/transforms, coordinate convention, interfaces, generator version and revision-bound mesh references. The BOM comes from that same manifest and leaves material, mass and cost unknown. Deterministic checks compare actual assembly bounds to the canonical overall envelope and calculate wheel centers from wheelbase/tracks.

Revision-bound outputs include component/assembly STL, assembly STEP, an A3 vector PDF with top/side/front projections and dimension labels, manifest JSON, BOM JSON, and a conceptual engineering note. Artifact metadata records checksums, generator version and coarse dependencies; changed revisions make prior outputs stale. The Studio uses the existing checksum- and revision-validated mesh pipeline and provides per-component visibility/selection, fit and standard views. EV front view aligns with the vehicle's X-forward coordinate convention.

**Engineering boundary:** these are packaging envelopes and illustrative mounting interfaces. The 300 km range is not calculated. There is no mass, energy/battery sizing, motor rating, structural strength, suspension dynamics, crashworthiness, thermal, regulatory, safety or manufacturing analysis. Assumed wheelbase, track, tires and package placements require review. A prompt change creates a reviewed new revision; persisted EV fields are not yet exposed in the general-purpose edit rail.

Sprint 5 verification is recorded below. Chrome acceptance exercised the EV prompt review and commit, all 27 current-revision component meshes, selection/visibility, front and ISO views, and layout PDF/manifest/BOM/STEP/STL downloads. It ran at 1440×900 and 1280×720 with no browser runtime or console errors. Screenshots and machine-readable evidence are kept in the ignored local `artifacts/` directory. This is a local acceptance check, not cross-browser or deployment testing.

### Sprint 5 verification record

- `npm test`: **69 Python tests and 13 Node tests passed**, with the existing Starlette/httpx deprecation warning.
- `npm run build:web`, standalone TypeScript, and JavaScript syntax checks passed.
- Chrome flow at 1440×900 and 1280×720: prompt proposal displayed evidence and editable assumptions; explicit commit created revision 2; all 27 component meshes returned HTTP 200 for that revision; WebGL canvas rendered; selection and first-click visibility toggling worked; front/ISO camera buttons worked; no runtime/console errors.
- Layout PDF, manifest JSON, BOM JSON, assembly STEP and STL returned HTTP 200 with matching revision and SHA-256 headers. Manifest and BOM each reported 27 components; PDF began with `%PDF-`.
- A 27-thread artifact-index publication check passed. Concurrent geometry requests had previously exposed a Windows atomic-replace race; artifact publication and index reads now use a process-local lock.
- Visual inspection confirmed the tires remain visible beyond the narrower body envelope and the 4,200 × 1,800 mm outer dimensions match the prompt. Browser screenshots: `artifacts/sprint5-ev-desktop.png` and `artifacts/sprint5-ev-1280x720.png`; structured results: `artifacts/sprint5-browser-acceptance.json`.

The local artifact-index lock does not provide a multi-process or multi-writer guarantee. Browser acceptance covers this Chrome environment and these two viewport sizes only.
