# Product roadmap

## MVP completion

1. Extend independent calculation references and geometry validation when adding supported gear profiles; current public equation references and fixed reference cases are documented in `engineering-reference-validation.md`, but they do not validate engagement or strength.
2. Add process-safe locking or transactional storage before allowing concurrent writers; add artifact index recovery and integrity checks.
3. Add browser acceptance checks and improve component explanations and evidence panels without overstating verification. Current environment has no browser surface or installed Playwright/browser runner, so browser acceptance remains unperformed.
4. Define explicit graph/dependency edges and a documented artifact lifecycle before adding more design families.
5. Connect a server-side language-model provider only after schema validation, fallback behavior, privacy controls, and evaluation benchmarks are in place.

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
