# Feature status

Status definitions: **Implemented** is present in this demonstrator; **Partial** has a deliberately narrow implementation; **Planned** is roadmap work; **Unsupported** is not represented as operational.

| Area / feature | Status | Scope |
|---|---|---|
| Design-family contract | Partial | Typed registry contains validated `spur_gear_pair@1.0` and `electric_vehicle@1.0`; both use the one canonical project file and revision history. |
| Prompt-to-system specification | Partial | `/api/v1/specifications/propose` returns evidence, assumptions, unresolved inputs, graph, and artifacts. Complete gear and bounded EV-envelope prompts can be reviewed and committed optimistically. Deterministic extraction is the default; optional model extraction only covers the existing typed spur-gear proposal. |
| Electric vehicle geometry | Partial | CadQuery generates 27 separately identified conceptual solids across frame, wheel/tire/hub/suspension, body, battery, motor, inverter, and reduction packages. Structural, crash, range, mass, dynamics, thermal, safety and production analyses remain unsupported. |
| New Design | Partial | Registry-driven initialization supports gear and EV families; replaces the single active project as a new revision and preserves history. Not independent multi-project storage. |
| Natural-language requirement extraction | Partial | Deterministic prompt parser extracts spur-gear values and a limited EV intake; optional local Ollama extraction returns an uncommitted typed spur-gear proposal behind an explicit setting. Evidence, ranges, missing/conflicting values remain visible; no automatic edit. |
| Dimensions, loads, operating inputs and objectives | Partial | Fixed typed numeric fields for ratio, torque, speed, module and width; no units parser or acceptance criteria. |
| Files, drawings, sketches and PDF ingestion | Unsupported | No parser or interpretation claim. |
| Missing/conflicting inputs and assumptions | Partial | Fixed assumptions are visible; no clarifying-question workflow. |
| Traceability, templates, requirement mapping | Planned | Not yet modeled. |
| Parametric geometry | Partial | Gear polygon solids plus separate CadQuery EV envelope solids. Both are conceptual/educational, not production-ready. |
| Named components and editable dimensions | Partial | Two named components, tooth counts and shared dimensions. |
| Browser viewport, orbit, zoom, pan, selection, visibility and presets | Partial | Three.js validates revision/component/unit/format and SHA-256 for each generated mesh; named selection and visibility controls map to scene meshes. No browser interaction test was available. |
| Viewport revision, fit, and component inspection | Partial | FIT frames visible generated mesh bounds; ISO/TOP/FRONT poses, disposal, component metadata, stale-response refresh and partial-component error display are implemented and unit/API tested. Real WebGL/browser acceptance remains unverified. |
| Assemblies, mates, clearances, exploded view, variants, undo/redo and comparison | Partial | EV assembly hierarchy, coordinate transforms and conceptual mounting/interface links; no constraint solver, interference check, or exploded view. |
| STEP / STL export | Partial | Genuine CadQuery/Open CASCADE gear or EV-envelope assembly and component exports; geometry is conceptual/educational only. |
| Geometry and unit checks | Partial | Numeric range validation plus vertex, bore, solid, bounds, and STEP/STL round-trip checks at tested boundaries; reference dimensions do not establish gear engagement. Pint dimensional arithmetic is used, but there is no general unit parser or interference check. |
| Torque/speed/ratio calculations | Partial | Ideal lossless gear ratio/speed/torque only. |
| Stress, deflection, thermal, safety factor and solver simulation | Unsupported | Explicit unknown/untested statuses. |
| Evidence, assumptions and status vocabulary | Partial | Typed verification states with summaries/evidence and revision-bound reports; overall valid designs remain PARTIAL, and failed inputs are not presented as mechanical failure. No general evidence graph. |
| Calculation traceability | Partial | Project responses include formula, substitution, units, assumptions, method version, reference note and calculation revision for supported gear values. |
| AeroPKmech Learn | Partial | One interactive, backend-calculated spur-gear lesson with quiz and browser-local progress. Other listed topics are explicitly planned. No connected AI tutor. |
| AeroPKmech Platform | Partial | Developer page inventories live FastAPI OpenAPI routes and provides local code examples and copy controls. No hosted API, API keys, accounts, quotas, or billing. |
| PK Intelligence evaluation | Partial | Synthetic v1 gear examples and v2 eight-task fixtures have provenance, split validation and hashes; paired candidate evaluator exists. No candidate-vs-base score has been executed. |
| Component explanations and learning | Partial | Selected-component Q&A receives canonical parameters, revision, assumptions and evidence; optional local inference is schema-validated, with deterministic fallback. No model was successfully inference-tested on this machine. |
| Design copilot / LLM adapter | Partial | Provider-neutral loopback Ollama adapter, output bounds, timeouts, readiness, schema validation and deterministic fallback. Model output cannot change canonical state or execute tools. |
| Revision history and invalidation | Partial | Prior project state retained; supported results recompute. Artifacts have a local checksum index and revision-based stale markers; no dependency graph or cross-process write coordination. |
| Atomic local project persistence | Implemented | Full candidate validation and same-directory atomic replace. Single-process/single-writer only; no lock or multi-writer guarantee. |
| Artifact metadata and historical retrieval | Partial | Revision/version/checksum metadata, stale listing and retained-file download; metadata index and artifact file are separate atomic writes, not one transaction. |
| PDF report and vehicle layout | Partial | ReportLab note plus A3 vector top/side/front projection of EV envelope geometry, with scale and revision; not a manufacturing drawing. |
| Data/model lab, evaluation, training controls | Partial | Dedicated Linux/WSL QLoRA package, hardware preflight, run metadata, paired evaluator, opt-in/redacted trace review/curation, and model lifecycle registry. No successful inference or training run; corpus is eight synthetic records. |
| Public API, keys, SDK, jobs and webhooks | Planned | Internal versioned routes only; no public deployment readiness. |
| Provenance, design diff, failure lab, sensitivity, optimization, notebook, collaboration | Planned | See roadmap. |
| Accounts, permissions, retention, teams and billing | Planned | Not implemented. |
