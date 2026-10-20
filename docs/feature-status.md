# Feature status

Status definitions: **Implemented** is present in this demonstrator; **Partial** has a deliberately narrow implementation; **Planned** is roadmap work; **Unsupported** is not represented as operational.

| Area / feature | Status | Scope |
|---|---|---|
| Design-family contract | Partial | Typed registry contains only validated `spur_gear_pair@1.0`; metadata and capabilities are API-discoverable. No second family is implemented. |
| Prompt-to-system specification | Partial | `/api/v1/specifications/propose` returns schema-versioned parameters, provenance, assumptions, unresolved inputs, a component hierarchy, and relationships. A complete spur gear pair can be reviewed and committed; an electric vehicle gets a conceptual rule-based hierarchy only, with no claimed CAD or calculations. No LLM is connected. |
| Electric vehicle decomposition | Conceptual only | A narrow prompt classifier recognizes electric road-vehicle requests and surfaces chassis, running gear, propulsion, thermal, electrical, and supervisory groups. Every vehicle node is marked `CONCEPTUAL_ONLY` with `generator_available: false`; no vehicle design, CAD, BOM quantities, mass estimate, or performance result is generated. |
| New Design | Partial | Registry-driven initialization for the gear family; replaces the single active local project as a new revision and preserves revision history. Not independent multi-project storage. |
| Natural-language requirement extraction | Partial | Deterministic prompt parser extracts spur-gear values and a limited EV intake (seats, length, width, range, electric intent); records evidence, ranges, missing/conflicting values. No automatic edit or LLM. |
| Dimensions, loads, operating inputs and objectives | Partial | Fixed typed numeric fields for ratio, torque, speed, module and width; no units parser or acceptance criteria. |
| Files, drawings, sketches and PDF ingestion | Unsupported | No parser or interpretation claim. |
| Missing/conflicting inputs and assumptions | Partial | Fixed assumptions are visible; no clarifying-question workflow. |
| Traceability, templates, requirement mapping | Planned | Not yet modeled. |
| Parametric geometry | Partial | CadQuery/Open CASCADE polygon-tooth solids for two gears; approximation is not involute geometry. |
| Named components and editable dimensions | Partial | Two named components, tooth counts and shared dimensions. |
| Browser viewport, orbit, zoom, pan, selection, visibility and presets | Partial | Three.js validates revision/component/unit/format and SHA-256 for each generated mesh; named selection and visibility controls map to scene meshes. No browser interaction test was available. |
| Viewport revision, fit, and component inspection | Partial | FIT frames visible generated mesh bounds; ISO/TOP/FRONT poses, disposal, component metadata, stale-response refresh and partial-component error display are implemented and unit/API tested. Real WebGL/browser acceptance remains unverified. |
| Assemblies, mates, clearances, exploded view, variants, undo/redo and comparison | Planned | Not implemented. |
| STEP / STL export | Partial | Genuine CadQuery/Open CASCADE assembly exports; profile remains an educational approximation. |
| Geometry and unit checks | Partial | Numeric range validation plus vertex, bore, solid, bounds, and STEP/STL round-trip checks at tested boundaries; reference dimensions do not establish gear engagement. Pint dimensional arithmetic is used, but there is no general unit parser or interference check. |
| Torque/speed/ratio calculations | Partial | Ideal lossless gear ratio/speed/torque only. |
| Stress, deflection, thermal, safety factor and solver simulation | Unsupported | Explicit unknown/untested statuses. |
| Evidence, assumptions and status vocabulary | Partial | Typed verification states with summaries/evidence and revision-bound reports; overall valid designs remain PARTIAL, and failed inputs are not presented as mechanical failure. No general evidence graph. |
| Calculation traceability | Partial | Project responses include formula, substitution, units, assumptions, method version, reference note and calculation revision for supported gear values. |
| AeroPKmech Learn | Partial | One interactive, backend-calculated spur-gear lesson with quiz and browser-local progress. Other listed topics are explicitly planned. No connected AI tutor. |
| AeroPKmech Platform | Partial | Developer page inventories live FastAPI OpenAPI routes and provides local code examples and copy controls. No hosted API, API keys, accounts, quotas, or billing. |
| PK Intelligence evaluation | Partial | Synthetic hand-authored splits and deterministic extraction evaluation harness. No training, external corpus, or independent engineering validation. |
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
