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
dataset, then checks for at least 8 GiB total VRAM, 16 GiB total RAM, 8 GiB
currently available RAM and 30 GiB free disk before loading a base model. It
records current free VRAM when `nvidia-smi` provides it. Failed or malformed
GPU telemetry and disk-capacity read errors block safely before model load.
These are conservative gates, not a peak-memory guarantee. It uses NF4 QLoRA, a frozen base and
adapter checkpoints. It writes run metadata but does not evaluate or promote
an adapter. Evaluation on the unchanged base and candidate, artifact
checksums, and human approval are separate required steps. Interrupted runs
resume from an existing trainer checkpoint when available.

The 2026-10-21 preflight measured an RTX 3050 Laptop GPU with **6 GiB total
VRAM** (**5.70 GiB free at latest measurement**), **15.69 GiB total RAM**
(**1.73 GiB currently available**) and **498.13 GiB free disk**. GPU VRAM,
total RAM and available RAM are below the configured training gate. The installed Ollama
0.40.6 service lists `qwen3:0.6b`, but a bounded GPU inference attempt failed
with CUDA OOM while requesting a 429,173,760-byte buffer. A CPU-only attempt
with a 512-token context and 32-token output failed with Windows `0xc0000409`
while allocating a 310,250,496-byte buffer. No response was generated. No
large model was downloaded and no fine-tuning run was attempted. A fresh
read-only Ollama probe on 2026-10-21 reaches the local service and finds
`qwen3:0.6b` installed, but reports `MODEL_INSTALLED_NOT_INFERRED`; no new
inference was attempted. The application model-selection variable is unset.
Do not bypass the training gate.

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
responses fall back to the deterministic parser; status distinguishes an
unavailable service, absent model, resource exhaustion, runtime crash, timeout
and invalid output. Readiness does not claim inference success. Every proposal
remains uncommitted until reviewed.

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
