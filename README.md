# AeroPKmech

An early, local engineering design environment for an educational external spur gear pair and a conceptual EV packaging assembly. It includes revisioned canonical state, deterministic gear calculations, a browser CAD mesh preview, a vector vehicle layout drawing, revision-bound artifacts, an interactive engineering lesson, and a local developer portal.

## Run locally

Requirements: Node.js 20.9 or newer, `uv`, and the project-local Python 3.12 runtime. Python, FastAPI, CadQuery/Open CASCADE, Pint, ReportLab and test tools are managed in `.python-install` and `.venv`; Next.js, React, TypeScript and Three.js are project npm dependencies. No API key is needed. All runtime assets are local.

```powershell
npm run dev
# Open http://127.0.0.1:3000
```

For production mode, run `npm run build:web` once, then `npm start` to launch the API and production web application together.

The app writes its one active project to `data/project.json` and generated CAD/report outputs plus `artifact-index.json` to `artifacts/`. Project writes validate the full candidate and replace the JSON file atomically. Artifact metadata records revision, generator/report version and SHA-256; older artifacts are retained and marked stale in `GET /api/v1/artifacts`. Persistence is single-process/single-writer and is not multi-writer safe. `npm test` runs API, engineering-reference, persistence, geometry, and frontend contract tests; `npm run build:web` checks the production Next.js build.

## Demonstration

Submit a supported gear prompt or the two-seat EV prompt. Review source-tagged inputs and assumed packaging defaults before committing. The EV creates separate frame, wheel/tire, body and propulsion packaging solids in CadQuery, with a shared project revision. Its Studio parameter panel edits 13 supported geometry dimensions against the current revision, regenerates and verifies candidate solids, then commits or displays validation/conflict errors. Generate STEP/STL, layout PDF, manifest and BOM from the artifact panel. The EV is conceptual packaging geometry: the 300 km value remains a target; mass, range calculation, strength, crashworthiness, safety, thermal design and production suitability are unsupported. Gear inputs keep their existing edit flow. Learn progress is browser-local. Optional local Ollama integration can propose uncommitted extraction results and answer selected-component questions using project context; deterministic calculations and CAD stay authoritative.

## Current API

- `GET /api/v1/health`
- `GET /api/v1/project`
- `PATCH /api/v1/project` with numeric fields `pinion_teeth`, `gear_teeth`, `module_mm`, `face_width_mm`, `input_torque_Nm`, `input_speed_rpm`
- `GET /api/v1/design-families`, `POST /api/v1/project/initialize`, and `POST /api/v1/project/demo`
- `POST /api/v1/project/interpret` returns a deterministic typed proposal by default; opt-in local model proposals pass the same schema and remain uncommitted
- `POST /api/v1/specifications/propose` returns a versioned reviewable spur-gear or EV packaging specification
- `POST /api/v1/project/vehicle/generate` commits reviewed EV parameters with an optimistic revision guard
- `PATCH /api/v1/project/vehicle` regenerates and verifies supported EV geometry parameters before a revision-conditional commit
- `GET /api/v1/vehicle/layout.pdf`, `/api/v1/vehicle/manifest.json`, `/api/v1/vehicle/bom.json` generates revision-linked vehicle artifacts
- `POST /api/v1/learn/spur-gear/experiment` calculates uncommitted lesson inputs with the same engineering core
- `GET /api/v1/export/stl`
- `GET /api/v1/export/step`
- `GET /api/v1/report`
- `GET /api/v1/report.pdf`
- `GET /api/v1/artifacts` lists retained artifacts and stale revisions
- `GET /api/v1/artifacts/{filename}` checksum-verifies and downloads a retained artifact
- `GET /api/v1/model/status`, `POST /api/v1/components/explain`, and `POST /api/v1/project/change-impact` provide optional local-model assistance and read-only component/change analysis
- `/api/v1/learning/*` provides opt-in redacted trace capture, human review/curation, and split validation; capture is disabled by default
- `/api/v1/models/registry*` provides checksummed candidate lifecycle, approval, activation, and rollback
- `GET /api/v1/model/status`, `POST /api/v1/components/explain`, and `POST /api/v1/project/change-impact` provide optional local model assistance and read-only component/change analysis
- `/api/v1/learning/*` provides opt-in redacted trace capture, human review/curation, and split validation; capture is disabled by default
- `/api/v1/models/registry*` provides checksummed candidate lifecycle, approval, activation, and rollback

PATCH errors use HTTP 422 with validation messages. Each accepted PATCH increments the revision and retains the prior full state in `history`.

## Limits

The gear boundary is a polygonal tooth approximation built as valid CadQuery/Open CASCADE solids. STEP and STL artifacts are genuine CAD-kernel exports, but the tooth profile is not an involute and is not manufacturing-ready. The demo omits bearings, housing, clearances, backlash, tolerances, material data, stress/strength, fatigue, thermal analysis, and solver-based simulation. The calculations do not establish safety or suitability for real machinery. Persistence is a single local JSON file; the application has no authentication, multi-user isolation, database, object store, or production security controls. Deterministic extraction remains the default; optional local-model inference has not passed a live smoke test on this machine.

## Development status

See [docs/api.md](docs/api.md), [docs/model-strategy.md](docs/model-strategy.md), [docs/feature-status.md](docs/feature-status.md), [docs/engineering-methods.md](docs/engineering-methods.md), [docs/engineering-reference-validation.md](docs/engineering-reference-validation.md), [docs/architecture.md](docs/architecture.md), [docs/security.md](docs/security.md), [docs/roadmap.md](docs/roadmap.md), [docs/sprint-3-audit.md](docs/sprint-3-audit.md), [docs/sprint-4-geometry-readability.md](docs/sprint-4-geometry-readability.md), [docs/completion-analysis-report.md](docs/completion-analysis-report.md), [data/learning/README.md](data/learning/README.md), and [ml-training/README.md](ml-training/README.md). Tooth strength and complete physical verification remain out of scope; successful model inference and training have not been established.
