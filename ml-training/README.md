# Isolated SLM training experiments

This package is separate from the FastAPI runtime and pins its direct ML
dependencies. It targets Linux/WSL with CUDA; `bitsandbytes` is not installed
into the web/API environment. Use a dedicated environment:

```bash
cd ml-training
uv sync
python scripts/validate_dataset.py ../data/learning/engineering-v2
python scripts/preflight.py
python scripts/train_qlora.py configs/qwen3-4b-qlora.json
python scripts/evaluate_models.py --base-model <base-runtime-name> --base-revision <base-sha> --candidate-model <candidate-runtime-name> --candidate-revision <candidate-sha> --output <evaluation-report.json>
```

The runner requires a full immutable Hugging Face commit SHA, validates the
dataset, then checks for at least 8 GiB VRAM, 16 GiB RAM and 30 GiB free disk
before loading a base model. It uses NF4 QLoRA, a frozen base and adapter
checkpoints. It writes run metadata but does not evaluate or promote an
adapter. Evaluation on the unchanged base and candidate, artifact checksums,
and human approval are separate required steps. Interrupted runs resume from
an existing trainer checkpoint when available.

The current machine has an RTX 3050 Laptop GPU with **6 GiB VRAM**, **15.69 GiB
system RAM**, and **500 GiB free disk**. GPU VRAM and system RAM are below the
configured training gate; no large model was downloaded and no fine-tuning run
was attempted. An inference attempt using the already-installed Qwen3 0.6B
failed at CUDA allocation with out-of-memory. Do not bypass the training gate.

The committed fixture set `engineering-v2.0.0` contains eight synthetic,
hand-authored records across eight task categories. It is only a development
fixture and is far too small to establish a useful domain model. Add reviewed,
licensed examples through the local curation flow before proposing a real
experiment. The test split remains held out; this initial short runner only
trains on `train.jsonl`. Validation scoring is not yet wired into the trainer.
The paired evaluator runs base and candidate on the same held-out examples and
reports JSON validity and exact expected-field subset accuracy. The two-record
test fixture is too small for statistical claims; approval remains manual.

Large model weights, adapters, caches and per-user trace data are ignored by
Git. Ollama is a separate inference service. Set `AEROPKMECH_OLLAMA_MODEL` to
an installed local model to enable it; set
`AEROPKMECH_ENABLE_MODEL_EXTRACTION=true` only to opt into model-assisted
gear extraction. No external API key is used. Unavailable or invalid model
responses fall back to the deterministic parser. Every proposal remains
uncommitted until reviewed.

## Base model candidates

- **Primary candidate: Qwen/Qwen3-4B**, model card says Apache-2.0, 4B
  parameters, Transformers support, BF16 weights and 8.06 GB repository size.
  Revision pinned in the example config: `1cfa9a7208912126459214e8b04321603b3df60c`.
- **Comparison candidate: Qwen/Qwen3-8B**, model card says Apache-2.0,
  Transformers support and 8B parameters. It is not downloaded; raw weights
  are larger still and do not fit the present VRAM budget for training.

The local 0.6B inference attempt failed because the currently available GPU
memory was insufficient; no inference-quality score is recorded. The Qwen
licenses and model cards are linked in
[`docs/model-strategy.md`](../docs/model-strategy.md). A local 0.6B Ollama
model is installed, but that failed smoke test does not establish that the 4B
candidate has been benchmarked.
