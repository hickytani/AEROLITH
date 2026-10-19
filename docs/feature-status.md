# Feature status

Status definitions: **Implemented** is present in this demonstrator; **Partial** has a deliberately narrow implementation; **Planned** is roadmap work; **Unsupported** is not represented as operational.

| Area / feature | Status | Scope |
|---|---|---|
| Natural-language requirement extraction | Partial | Deterministic family-scoped parser extracts typed inputs and explicit evidence; reports missing/conflicting values, no automatic edit, no LLM. |
| Dimensions, loads, operating inputs and objectives | Partial | Fixed typed numeric fields for ratio, torque, speed, module and width; no units parser or acceptance criteria. |
| Files, drawings, sketches and PDF ingestion | Unsupported | No parser or interpretation claim. |
| Missing/conflicting inputs and assumptions | Partial | Fixed assumptions are visible; no clarifying-question workflow. |
| Traceability, templates, requirement mapping | Planned | Not yet modeled. |
| Parametric geometry | Partial | CadQuery/Open CASCADE polygon-tooth solids for two gears; approximation is not involute geometry. |
| Named components and editable dimensions | Partial | Two named components, tooth counts and shared dimensions. |
| Browser viewport, orbit, zoom, pan, selection, visibility and presets | Partial | Three.js viewer loads the generated component STL from the backend; interaction is in place. |
| Assemblies, mates, clearances, exploded view, variants, undo/redo and comparison | Planned | Not implemented. |
| STEP / STL export | Partial | Genuine CadQuery/Open CASCADE assembly exports; profile remains an educational approximation. |
| Geometry and unit checks | Partial | Numeric range validation plus vertex, bore, solid, bounds, and STEP/STL round-trip checks at tested boundaries; reference dimensions do not establish gear engagement. Pint dimensional arithmetic is used, but there is no general unit parser or interference check. |
| Torque/speed/ratio calculations | Partial | Ideal lossless gear ratio/speed/torque only. |
| Stress, deflection, thermal, safety factor and solver simulation | Unsupported | Explicit unknown/untested statuses. |
| Evidence, assumptions and status vocabulary | Partial | Typed verification states with summaries/evidence and revision-bound reports; overall valid designs remain PARTIAL, and failed inputs are not presented as mechanical failure. No general evidence graph. |
| Component explanations and learning | Planned | This interface is a design study; no lesson engine. |
| Design copilot / LLM adapter | Unsupported | No provider connection or AI edit path. |
| Revision history and invalidation | Partial | Prior project state retained; supported results recompute. Artifacts have a local checksum index and revision-based stale markers; no dependency graph or cross-process write coordination. |
| Atomic local project persistence | Implemented | Full candidate validation and same-directory atomic replace. Single-process/single-writer only; no lock or multi-writer guarantee. |
| Artifact metadata and historical retrieval | Partial | Revision/version/checksum metadata, stale listing and retained-file download; metadata index and artifact file are separate atomic writes, not one transaction. |
| PDF report | Implemented | ReportLab produces a revision-bound PDF and FastAPI also serves the HTML report. |
| Data/model lab, evaluation, training controls | Planned | No project training use. |
| Public API, keys, SDK, jobs and webhooks | Planned | Internal versioned routes only; no public deployment readiness. |
| Provenance, design diff, failure lab, sensitivity, optimization, notebook, collaboration | Planned | See roadmap. |
| Accounts, permissions, retention, teams and billing | Planned | Not implemented. |
