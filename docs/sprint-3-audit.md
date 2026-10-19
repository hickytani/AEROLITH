# Sprint 3 repository audit

**Audit date:** 2026-10-19
**Workspace:** `C:\Users\prasu\Downloads\aeromech`

## Verified repository state

- The API is FastAPI/Pydantic under `services/api/aeropkmech`; Next.js 16 App Router wraps the legacy Studio markup in `apps/web/app/WorkspaceShell.tsx`; `public/app.js` owns the Three.js viewer and Studio interactions.
- `npm run dev` starts API plus web; `npm run api`, `npm run web`, `npm test`, and `npm run build:web` are declared in `package.json`.
- The canonical state is one `Design` with `id`, `family`, `schema_version`, `revision`, `requirements`, `components`, `assumptions`, `status`, and `history`. `store.save` validates and atomically replaces one local JSON file. There is no multi-project store or writer lock.
- `GET /api/v1/project` computes derived values and verification from one loaded state. Artifact metadata already records revision, kind, version and SHA-256; files are retained and stale entries are marked. File and index writes are separate operations.
- The implementation is one `spur_gear_pair`; its domain-specific calculations are in `engineering.py`, polygonal CAD is in `cad.py`, and the requirement parser is deterministic. No motor, aerospace, robotics or general-CAD family is implemented.
- The Studio `/` page is built from `public/index.html` and `public/app.js`. Its navigation displayed Learn as “preview” and Platform as “planned”; both were plain spans without destinations.
- Git was on `codex/sprint-2-engineering-validation`, tracking origin, with PR #1 targeting `main`. At audit start `apps/web/next-env.d.ts` was modified; it points to the generated `.next/dev/types` files. This pre-existing working-tree change is preserved.

## Confirmed Apply changes defect

`public/app.js` handles Apply by sending `PATCH /api/v1/project`, assigning its successful response to the canonical in-memory `project`, then calling `build()` and `fill()`. The API update therefore succeeds and persists before the reported exception. `fill()` calls `getElementById("components").querySelector(...)`, but the markup contained a `.components` class without an `id="components"`; this yields the reported null `querySelector` access. The earlier assignments in `fill()` update result fields before the throw, while the component output label remains hardcoded as `OUTPUT · 3:1`.

This defect is in the initial markup/DOM contract, not in the API update. A failed API PATCH is rejected before persistence by full candidate validation and atomic save. A frontend render failure after a successful PATCH is different: the persisted revision has already advanced. Sprint 3 fixes the selector at its source, computes component labels from the same response, restores the last committed field values on API failure, and serializes UI edits to avoid stale overlapping responses.

## Confirmed versus unverified

Verified by source inspection: current API routes and contracts, atomic single-file project persistence, artifact checksum/stale behavior, CAD geometry scope, deterministic requirement parsing, and the DOM null dereference above. Prior Sprint 2 test record: 43 Python tests passed; Next build and JavaScript syntax checks passed.

Not established by repository inspection: browser-level acceptance, visual correctness on a real browser/GPU, physical tooth engagement, strength/fatigue/thermal behavior, production security, concurrent writer safety, multi-project persistence, or any implemented capability outside the spur-gear family. No browser runner was installed or exposed at audit start.

## Sprint 3 architectural boundary

The design-family registry will expose only implementations with working validation, calculations, geometry/export support and limitations. New Design is an honest initialization flow over the existing single canonical project; it will not claim multiple independent projects. Learn will experiment through the backend gear calculation implementation and retain completion locally in that browser. Platform will enumerate the live FastAPI OpenAPI contract and give local unauthenticated examples; hosted keys, accounts and public service remain unavailable.

## Sprint 3 verification results

- `npm test`: 51 Python tests passed and 4 Node frontend contract tests passed. Pytest emitted one existing Starlette/httpx deprecation warning.
- `npm run build:web`: passed, including compilation, TypeScript and static generation for `/`, `/designs/new`, `/learn`, and `/platform`.
- Standalone TypeScript and `node --check` checks passed for the frontend and launcher.
- Live local smoke check returned HTTP 200 for all four pages, served the family registry, served a 15-path OpenAPI document, and returned the expected 12/30-tooth lesson results (2.5 ratio, 42 mm center distance, 360 rpm, 20 N·m ideal torque). The experiment did not change project state. The API used isolated temporary data and artifact directories.
- Browser visual acceptance remains unverified because the available computer-use inventory is empty (`apps: []`, `browsers: []`) and no local browser automation runner is available. The live HTTP check does not establish visual layout, WebGL behavior, or browser download interactions.
