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

The fully supported output path remains the spur gear pair: a complete request can be reviewed and committed, after which real existing CadQuery geometry, ideal calculations, reports and exports are available at the new project revision. Gear extraction is deterministic and does not call an LLM.

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

No changes were committed or pushed for this milestone; the directive requires explicit authorization for those Git operations.
