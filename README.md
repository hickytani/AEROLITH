# AeroPKmech

An early, local engineering design environment for an educational external spur gear pair. It includes a revisioned design state, deterministic gear-ratio and pitch-geometry calculations, range validation, a browser 3D mesh preview, revision-bound artifacts, an interactive engineering lesson, and a local developer portal.

## Run locally

Requirements: Node.js 20.9 or newer, `uv`, and the project-local Python 3.12 runtime. Python, FastAPI, CadQuery/Open CASCADE, Pint, ReportLab and test tools are managed in `.python-install` and `.venv`; Next.js, React, TypeScript and Three.js are project npm dependencies. No API key is needed. All runtime assets are local.

```powershell
npm run dev
# Open http://127.0.0.1:3000
```

For production mode, run `npm run build:web` once, then `npm start` to launch the API and production web application together.

The app writes its one active project to `data/project.json` and generated CAD/report outputs plus `artifact-index.json` to `artifacts/`. Project writes validate the full candidate and replace the JSON file atomically. Artifact metadata records revision, generator/report version and SHA-256; older artifacts are retained and marked stale in `GET /api/v1/artifacts`. Persistence is single-process/single-writer and is not multi-writer safe. `npm test` runs API, engineering-reference, persistence, geometry, and frontend contract tests; `npm run build:web` checks the production Next.js build.

## Demonstration

Open the workspace, change the pinion or gear tooth count, then select **Apply changes**. The server validates the request, persists a new history revision, returns calculations and verification tied to that revision, and refreshes the viewport from generated geometry. The viewer checks each component STL revision, identity, millimetre units, format and SHA-256 before rendering; a failed component is reported independently. The interface uses a local system-font stack. Use **New design** for registry-backed initialization, **Learn** for the interactive gear lesson, and **Platform** for the live local API reference. Learn progress is browser-local. Example state: 18/54 teeth, module 2 mm, width 12 mm, ratio 3:1, center distance 72 mm, 300 rpm ideal output speed and 24 N·m ideal output torque.

## Current API

- `GET /api/v1/health`
- `GET /api/v1/project`
- `PATCH /api/v1/project` with numeric fields `pinion_teeth`, `gear_teeth`, `module_mm`, `face_width_mm`, `input_torque_Nm`, `input_speed_rpm`
- `GET /api/v1/design-families`, `POST /api/v1/project/initialize`, and `POST /api/v1/project/demo`
- `POST /api/v1/project/interpret` returns a deterministic typed proposal with evidence, missing inputs and conflicts; no LLM extraction is claimed
- `POST /api/v1/learn/spur-gear/experiment` calculates uncommitted lesson inputs with the same engineering core
- `GET /api/v1/export/stl`
- `GET /api/v1/export/step`
- `GET /api/v1/report`
- `GET /api/v1/report.pdf`
- `GET /api/v1/artifacts` lists retained artifacts and stale revisions
- `GET /api/v1/artifacts/{filename}` checksum-verifies and downloads a retained artifact

PATCH errors use HTTP 422 with validation messages. Each accepted PATCH increments the revision and retains the prior full state in `history`.

## Limits

The gear boundary is a polygonal tooth approximation built as valid CadQuery/Open CASCADE solids. STEP and STL artifacts are genuine CAD-kernel exports, but the tooth profile is not an involute and is not manufacturing-ready. The demo omits bearings, housing, clearances, backlash, tolerances, material data, stress/strength, fatigue, thermal analysis, and solver-based simulation. The calculations do not establish safety or suitability for real machinery. Persistence is a single local JSON file; the application has no authentication, multi-user isolation, database, object store, or production security controls. Requirement extraction is deterministic pattern matching, not an LLM.

## Development status

See [docs/api.md](docs/api.md), [docs/model-strategy.md](docs/model-strategy.md), [docs/feature-status.md](docs/feature-status.md), [docs/engineering-methods.md](docs/engineering-methods.md), [docs/engineering-reference-validation.md](docs/engineering-reference-validation.md), [docs/architecture.md](docs/architecture.md), [docs/security.md](docs/security.md), [docs/roadmap.md](docs/roadmap.md), [docs/sprint-3-audit.md](docs/sprint-3-audit.md), [docs/sprint-4-geometry-readability.md](docs/sprint-4-geometry-readability.md), [docs/completion-analysis-report.md](docs/completion-analysis-report.md), and [data/learning/README.md](data/learning/README.md). Tooth strength, complete physical verification, a connected tutor, and model training remain out of scope.
