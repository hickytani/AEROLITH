# Engineering intelligence and model strategy

The current intake uses deterministic patterns for one design family. It is deliberately small, transparent and testable. It records matched text as evidence, validates values against a strict Pydantic schema, identifies missing fields and detects a stated gear-ratio conflict with explicit tooth counts. It never edits project state or fills missing values from the demo design.

`RequirementProvider` is the replaceable asynchronous provider interface. Future LLM results must return only the typed proposal, pass Pydantic validation, and remain a user-reviewed proposal. Model output cannot run code or commands and cannot set calculation/verification results. Deterministic calculations stay authoritative.

There is no model training or remote inference configured. Training would be premature without permissioned inputs, independent outcome labels, a held-out evaluation set and a demonstrated benefit over this baseline. Private project data is not collected for training. Planned evaluation should include schema validity, omissions and conflicts, question quality, revision edit success, numerical consistency, unsupported-claim rate and failure handling.
