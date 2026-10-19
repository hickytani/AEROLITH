# Requirement interpretation evaluation data

This versioned dataset covers the narrow task “natural-language engineering request → structured, reviewable spur-gear specification”. The JSONL examples are synthetic and hand-authored. Expected values are recorded separately from the parser and manually checked for slot extraction, ratio arithmetic, unit conversion, and explicit ratio conflicts.

The manifest identifies the local license status. No third-party or user-project text is included. The repository has no LICENSE file, so examples are not offered under a separate public license. Do not add external examples until their provenance and redistribution rights are recorded.

`train.jsonl`, `validation.jsonl`, and `test.jsonl` are split before running evaluation. The deterministic harness evaluates all three without fitting a model:

```powershell
uv run --cache-dir .uv-cache python -m aeropkmech.evaluation
```

The held-out cases test parser behavior only. This small dataset is not statistically representative, is not a specialist-model training corpus, and provides no independent evidence about gear calculations, strength, safety, or manufacturing suitability. No model training or external provider call is performed.
