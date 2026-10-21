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
| POST | `/api/v1/project/change-impact` | Revision-bound, read-only impact preview for supported parameter names. |
| POST | `/api/v1/specifications/propose` | Return a versioned, reviewable spur-gear or EV packaging proposal; never mutates project state. |
| POST | `/api/v1/project/vehicle/generate` | Optimistically commit a reviewed, schema-validated EV packaging design into the shared project store. |
| POST | `/api/v1/learn/spur-gear/experiment` | Calculate uncommitted lesson parameters with the same deterministic gear core. |
| GET | `/api/v1/platform/openapi` | Live OpenAPI document for the developer portal; hidden from its own endpoint inventory. |
| GET | `/api/v1/geometry/{component_id}.stl` | Current-revision gear or EV component mesh for the viewer. |
| GET | `/api/v1/export/stl` | Current-revision assembly STL. |
| GET | `/api/v1/export/step` | Current-revision assembly STEP. |
| GET | `/api/v1/report` | Current-revision HTML engineering note. |
| GET | `/api/v1/report.pdf` | Current-revision PDF engineering note. |
| GET | `/api/v1/vehicle/layout.pdf` | Revision-bound vector top/side/front EV envelope layout drawing. |
| GET | `/api/v1/vehicle/manifest.json` | Revision-bound component hierarchy, dimensions, transforms, interfaces and mesh references. |
| GET | `/api/v1/vehicle/bom.json` | Preliminary BOM from generated geometry; materials, mass and cost remain null. |
| GET | `/api/v1/artifacts` | List indexed artifacts and flag prior revisions as stale. |
| GET | `/api/v1/artifacts/{filename}` | Retrieve a retained, checksum-verified artifact; response includes stale state. |
| GET | `/api/v1/model/status` | Loopback service reachability, exact model installation, and active registry metadata; it does not claim inference success. |
| POST | `/api/v1/components/explain` | Answer a bounded selected-component question using canonical context; returns inference status or deterministic fallback without changing design state. |
| GET | `/api/v1/learning/dataset/status?version=...` | Verify provenance, licenses, split membership, hashes and dataset version. |
| POST | `/api/v1/learning/traces` | Capture a redacted local execution trace only when collection is enabled and request opts in. |
| POST | `/api/v1/learning/traces/{id}/review` | Record an explicit local review decision. |
| POST | `/api/v1/learning/traces/{id}/curate` | Add an approved trace plus reviewed target/provenance to the curated dataset. |
| DELETE | `/api/v1/learning/traces/{id}` | Move raw trace to ignored local quarantine. |
| GET/POST/PATCH | `/api/v1/models/registry...` | Read registry, register checksummed candidate metadata, and apply controlled lifecycle transitions. |
| POST | `/api/v1/models/registry/rollback` | Reactivate recorded previous approved local runtime model. |
| POST | `/api/v1/engineering/tools/validate-proposal` | Validate an allowlisted, revision-bound tool proposal; never executes it. |

PATCH body fields: `pinion_teeth` (8–80 integer), `gear_teeth` (8–120 integer), `input_torque_Nm` (>0), `input_speed_rpm` (>0), `module_mm` (0.5–6), `face_width_mm` (2–60). Unknown fields are rejected. The gear ratio is derived from tooth counts. A successful edit returns the complete new design state. Validation errors use FastAPI's structured HTTP 422 response.

The interpretation endpoint returns user evidence plus explicitly assumed EV packaging parameters. A complete EV proposal can be reviewed and generated; prompt values retain source/evidence, while missing wheelbase, tracks, body height and tire dimensions get visible, editable conceptual defaults. POST `/project/vehicle/generate` requires `expected_revision`; stale proposals receive HTTP 409. The EV family shares the same single project file and history with the gear family. Its actual CadQuery envelopes are conceptual, not safety, performance or production engineering. Project responses include calculated dimension/wheel placement checks and explicit unresolved/unsupported statuses. EV exports include STEP/STL, per-component STL, PDF layout, manifest and BOM JSON. Artifacts record revision, generator version, hash and coarse dependency keys; prior-revision artifacts are stale and retained. The learning experiment route does not persist supplied parameters.

The geometry route accepts an optional `revision` query parameter. If it differs from the canonical revision, or the project changes while tessellation is running, the API returns HTTP 409 with the current revision in `X-Design-Revision`; it will not return a mesh from a different revision under the requested identifier. Successful component mesh responses use `model/stl`, `Cache-Control: no-store`, and carry `X-Geometry-Component-ID`, `X-Geometry-Revision`, `X-Geometry-Units: mm`, `X-Geometry-Format: stl`, `X-Artifact-ID`, and `X-Artifact-SHA256` alongside generator/version headers. The browser verifies these fields and the bytes before constructing a Three.js mesh. Experiment request fields match the gear parameters and use the same numeric bounds as the project model; invalid input returns HTTP 422 and does not create a project revision.

The local Platform page derives its endpoint inventory from the live OpenAPI document instead of maintaining a separate route list. Local API access has no authentication; do not expose this single-project, single-writer service as a public multi-tenant API. API-key issuance and hosted services are not implemented.

Model extraction is disabled unless `AEROPKMECH_ENABLE_MODEL_EXTRACTION=true` and a loopback Ollama model is configured. `/api/v1/model/status` checks service reachability and the exact model tag but marks `inference_tested: false`; only an actual schema-valid answer is reported as `INFERENCE_SUCCEEDED`. `POST /api/v1/components/explain` uses the active registry model, if one is approved, or `AEROPKMECH_OLLAMA_MODEL`; absent/unavailable inference falls back to deterministic component context and exposes a bounded failure status. Model responses cannot mutate project state or execute validated tool proposals. Training capture requires both `AEROPKMECH_ENABLE_TRAINING_CAPTURE=true` and `opt_in: true`; captured data is redacted and remains raw/unreviewed until explicitly approved and curated. See [model strategy](model-strategy.md) for training isolation and current hardware limits.

Local quick start:

```powershell
npm run dev
Invoke-RestMethod http://127.0.0.1:8000/api/v1/project
```

PATCH requests may include any non-empty subset of `pinion_teeth` (integer 8–80), `gear_teeth` (integer 8–120), `module_mm` (0.5–6), `face_width_mm` (2–60), `input_torque_Nm` (>0), and `input_speed_rpm` (>0). An optional `expected_revision` makes the edit conditional on the revision the user reviewed; a mismatch returns 409 without changing the project. A successful edit increments `revision` once and returns new calculations/verification with that revision. A 422 leaves prior persisted state unchanged. Multi-process writers remain unsupported.
