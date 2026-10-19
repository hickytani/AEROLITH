# Internal API reference

The API is versioned under `/api/v1`; FastAPI's interactive schema is available at `/docs` while the service is running.

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Service/kernel readiness. |
| GET | `/api/v1/project` | Canonical project revision, parameters, derived values, statuses, validation. |
| PATCH | `/api/v1/project` | Apply allowlisted numeric parameter edits; accepted edits create a revision. |
| POST | `/api/v1/project/interpret` | Deterministic, bounded natural-language extraction proposal. |
| GET | `/api/v1/geometry/{pinion|gear}.stl` | Current-revision component mesh for the viewer. |
| GET | `/api/v1/export/stl` | Current-revision assembly STL. |
| GET | `/api/v1/export/step` | Current-revision assembly STEP. |
| GET | `/api/v1/report` | Current-revision HTML engineering note. |
| GET | `/api/v1/report.pdf` | Current-revision PDF engineering note. |
| GET | `/api/v1/artifacts` | List indexed artifacts and flag prior revisions as stale. |
| GET | `/api/v1/artifacts/{filename}` | Retrieve a retained, checksum-verified artifact; response includes stale state. |

PATCH body fields: `pinion_teeth` (8–80 integer), `gear_teeth` (8–120 integer), `input_torque_Nm` (>0), `input_speed_rpm` (>0), `module_mm` (0.5–6), `face_width_mm` (2–60). Unknown fields are rejected. The gear ratio is derived from tooth counts. A successful edit returns the complete new design state. Validation errors use FastAPI's structured HTTP 422 response.

The interpretation endpoint returns a validated proposal, source text spans, missing fields and conflict messages. It does not commit a project revision; the user reviews all values and explicitly applies them through PATCH. Export/report responses include `X-Design-Revision`, `X-Generator-Version`, `X-Artifact-SHA256`, and `X-Artifact-Stale`. Artifacts are generated from a single loaded project snapshot and indexed in the local artifact directory. Stale artifacts are retained and may be retrieved via their indexed filename; current export routes generate the current revision.
