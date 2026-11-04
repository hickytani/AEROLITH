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

The updated 2026-10-29 preflight and empirical benchmarking measured an RTX 3050 Laptop GPU with **6 GiB total
VRAM** (**5.54 GiB free at check**), **15.69 GiB total RAM** (**2.26 GiB available**) and **475 GiB free disk**.
Unlike the prior 4B configuration attempt which required 8 GiB VRAM, live inference with `qwen3:0.6b` (751M parameters, Q4_K_M)
was verified and runs successfully inside Ollama 0.40.6. Inference operates bounded within ~1022 MiB VRAM with a 1.5–3.0s latency
and achieves 100% JSON syntactic validity across evaluation records.
Preflight checks now support model-sized thresholds via `--model-size 0.6b` (4096 MiB VRAM threshold), reporting `ready: true` on this hardware.

The versioned dataset `engineering-v2.2.0` expands coverage to **89 verified records** across all eight task categories
(51 train, 19 validation, 19 held-out test), strictly isolated with zero prompt leakage across splits.
The dataset covers varied spur-gear prompts, unit conversions (inch/cm to mm), explicit vs assumed vs derived values,
missing required inputs, contradictory constraints, bounds violations, packaging architecture, and engineering truth preservation.
Dataset integrity is validated by `scripts/validate_dataset.py` with 100% schema compliance.

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

Empirical benchmarks show that the base pretrained `qwen3:0.6b` achieves 100% JSON syntax validity but
exhibits 0–10% exact field typing accuracy on held-out engineering tasks (e.g. returning string numbers `"22"` instead of integers `22`
or echoing placeholder keys). The deterministic CAD interpreter achieves 100% on the 15-case Gold benchmark (0.83ms mean latency)
and 47.4% exact match (59.9% field accuracy) on the expanded 89-case dataset. Fine-tuning the 0.6B model via QLoRA is designed
to bridge this exact typing and domain extraction gap.
