# Internal API reference

The API is versioned under `/api/v1`; FastAPI's interactive schema is available at `/docs` while the service is running.

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Service/kernel readiness. |
| GET | `/api/v1/design-families` | Read-only registered family metadata and planned areas. |
| GET | `/api/v1/project` | Canonical project revision, parameters, derived values, statuses, validation. |
| PATCH | `/api/v1/project` | Apply allowlisted numeric parameter edits; accepted edits create a revision. |
| POST | `/api/v1/project/initialize` | Initialize a registered family with validated defaults, replacing the one active local project while preserving history. |
| POST | `/api/v1/project/demo` | Restore default demo state as a new revision. |
| POST | `/api/v1/project/interpret` | Deterministic, bounded natural-language extraction proposal. |
| POST | `/api/v1/learn/spur-gear/experiment` | Calculate uncommitted lesson parameters with the same deterministic gear core. |
| GET | `/api/v1/platform/openapi` | Live OpenAPI document for the developer portal; hidden from its own endpoint inventory. |
| GET | `/api/v1/geometry/{pinion|gear}.stl` | Current-revision component mesh for the viewer. |
| GET | `/api/v1/export/stl` | Current-revision assembly STL. |
| GET | `/api/v1/export/step` | Current-revision assembly STEP. |
| GET | `/api/v1/report` | Current-revision HTML engineering note. |
| GET | `/api/v1/report.pdf` | Current-revision PDF engineering note. |
| GET | `/api/v1/artifacts` | List indexed artifacts and flag prior revisions as stale. |
| GET | `/api/v1/artifacts/{filename}` | Retrieve a retained, checksum-verified artifact; response includes stale state. |

PATCH body fields: `pinion_teeth` (8–80 integer), `gear_teeth` (8–120 integer), `input_torque_Nm` (>0), `input_speed_rpm` (>0), `module_mm` (0.5–6), `face_width_mm` (2–60). Unknown fields are rejected. The gear ratio is derived from tooth counts. A successful edit returns the complete new design state. Validation errors use FastAPI's structured HTTP 422 response.

The interpretation endpoint returns a validated proposal, source text spans, missing fields and conflict messages. It does not commit a project revision; the user reviews all values and explicitly applies them through PATCH. Project responses include calculation provenance and verification generated from the same loaded revision. Export/report responses include `X-Design-Revision`, `X-Generator-Version`, `X-Artifact-SHA256`, and `X-Artifact-Stale`. Artifacts are generated from a single loaded project snapshot and indexed in the local artifact directory. Stale artifacts are retained and may be retrieved via their indexed filename; current export routes generate the current revision. The learning experiment route does not persist its supplied parameters.

The geometry route accepts an optional `revision` query parameter. If it differs from the canonical revision, the API returns HTTP 409 with the current revision in `X-Design-Revision`; it will not return a mesh from a different revision under the requested identifier. Experiment request fields match the gear parameters and use the same numeric bounds as the project model; invalid input returns HTTP 422 and does not create a project revision.

The local Platform page derives its endpoint inventory from the live OpenAPI document instead of maintaining a separate route list. Local API access has no authentication; do not expose this single-project, single-writer service as a public multi-tenant API. API-key issuance and hosted services are not implemented.

Local quick start:

```powershell
npm run dev
Invoke-RestMethod http://127.0.0.1:8000/api/v1/project
```

PATCH requests may include any non-empty subset of `pinion_teeth` (integer 8–80), `gear_teeth` (integer 8–120), `module_mm` (0.5–6), `face_width_mm` (2–60), `input_torque_Nm` (>0), and `input_speed_rpm` (>0). A successful edit increments `revision` once and returns new calculations/verification with that revision. A 422 leaves prior persisted state unchanged. Concurrent writers remain unsupported.
