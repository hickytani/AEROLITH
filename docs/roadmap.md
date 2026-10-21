# Product roadmap

## MVP completion

1. Extend independent calculation references and geometry validation when adding supported gear profiles; current public equation references and fixed reference cases are documented in `engineering-reference-validation.md`, but they do not validate engagement or strength.
2. Add process-safe locking or transactional storage before allowing concurrent writers; add artifact index recovery and integrity checks.
3. Expand browser acceptance to cover model-configured component Q&A, trace consent/curation UX, and model-registry controls. Sprint 5 browser acceptance for the Studio is recorded in the completion report; the integrated model work has API-level tests but no model UI inference session was available.
4. Define explicit graph/dependency edges and a documented artifact lifecycle before adding more design families.
5. Collect a permissioned, human-reviewed corpus and execute paired base/candidate evaluation on sufficient Linux/WSL CUDA hardware before training or activating an adapter. The optional local Ollama adapter is schema-validated and falls back deterministically; successful inference is not yet established.

## Current prompt-generation milestone

The prompt intake has a versioned proposal contract for gear and a bounded EV envelope family. The EV path creates separate CadQuery frame members, four tire/rim/hub/suspension-link sets, axle references, a body envelope, and battery/motor/inverter/reduction packaging solids. It produces revision-linked STL/STEP, PDF layout, manifest and preliminary BOM. Revision-conditional editing regenerates and checks candidate geometry before commit, and Studio exposes the review flow. Accepted source prompts and parameter evidence now flow into the canonical revision; gear responses and EV manifest/BOM expose the requirement-to-component mapping and parameter provenance. Unsupported scope and conceptual relationships remain explicit. Geometry is conceptual. Next work: independently validate or extend a genuine assembly/interface model and add interference checks with a defined contact method. No range, mass, strength, dynamics, crash or safety calculation is delivered. The spur-gear family also produces a revision-bound reference-layout PDF; a validated involute profile and manufacturing drawing remain future work.

## Next release

- Project accounts, secure sessions, ownership, audit records, privacy/retention settings, API authentication and rate limits.
- Better gear family coverage, supported clearances/mates, shafts and assembly tree after validation.
- CAD-kernel browser artifact exchange, STEP where supported, revision comparison, undo/redo, and artifact dependency tracking.
- Standards-scoped tooth calculations with material provenance, explicit criteria and independent benchmarks.
- Source-grounded component lessons, parameter-linked explanations and supported learning experiments.
- Reliable asynchronous artifact jobs, operational logging and artifact retention controls.

## Future development

- Drawing/PDF/image ingestion after parser/model validation; generalized requirements, project templates and traceability.
- Solver integrations (e.g. CalculiX, OpenFOAM or SU2) only for bounded workflows validated against independent cases; no generic solver claims.
- Sensitivity/uncertainty, Pareto trade-offs and optimization only with defined objectives and evidence.
- Curated authorized data, held-out model benchmarks and specialist-model evaluation; no silent use of private projects for training.
- Developer APIs, SDKs, integrations, collaboration/review, educator workspaces, localization and commercial usage management.
- Design diff visualization, failure lab, constraint conflict resolver, CAD-aware visual QA, notebook, challenge mode, manufacturing feasibility, reproducibility locks and benchmark dashboards.
