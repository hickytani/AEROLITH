# Engineering intelligence and local model strategy

## Current architecture

Gear and EV prompt interpretation still uses deterministic, reviewable proposal
code in `services/api/aeropkmech/intelligence.py`. It retains source evidence,
unresolved fields, assumptions, and family capability boundaries. The local
model is an optional second proposal source; it never writes project state or
determines CAD, calculations, verification, safety, or artifact validity. All
accepted requirement values pass the existing Pydantic schema, and edits still
require a revision-conditional user action.

`services/api/aeropkmech/model_platform.py` supplies a provider-neutral
interface with an Ollama loopback adapter, component-context Q&A, strict
response schemas, bounded prompts/timeouts, allowlisted revision-bound tool
proposals, data redaction, split validation, and model-registry lifecycle.
Component context comes from the active canonical design and selected
component. Invalid, unavailable, or stale model responses use deterministic
context. A model cannot execute the proposed tool or edit a design.

## Enable local inference

Install and start Ollama separately, then select an installed local model:

```powershell
$env:AEROPKMECH_OLLAMA_MODEL = "qwen3:4b"
$env:AEROPKMECH_ENABLE_MODEL_EXTRACTION = "true" # optional; default false
npm run dev
```

The Ollama adapter rejects non-loopback URLs, sends no API credentials, uses
bounded input/output and timeouts, and provides `GET /api/v1/model/status`.
Model-assisted extraction is opt-in; component Q&A uses a configured local
model. If Ollama is unavailable, deterministic workflows remain active. The
Studio component question panel sends only the selected component, committed
parameter context, revision, assumptions/evidence, and the question.

## Model choice and hardware evidence

The primary candidate is **Qwen/Qwen3-4B**, pinned in
`ml-training/configs/qwen3-4b-qlora.json` to immutable repository commit
`1cfa9a7208912126459214e8b04321603b3df60c`. Its model card lists Apache-2.0,
4.0B parameters, Transformers support, and an 8.06 GB repository size; the
card's example uses `AutoModelForCausalLM` and `device_map="auto"`.
[Qwen3-4B model card](https://huggingface.co/Qwen/Qwen3-4B)

Qwen3-8B is a comparison candidate only. Its model card lists Apache-2.0,
8B parameters, and Transformers support. It is not downloaded.
[Qwen3-8B model card](https://huggingface.co/Qwen/Qwen3-8B)

Hardware preflight on 2026-10-21 detected an NVIDIA GeForce RTX 3050 6GB
Laptop GPU (6,144 MiB total, 5,834 MiB free at the latest check, driver
581.95), 15.69 GiB total system RAM, 1.73 GiB currently available RAM, and
498.13 GiB free disk. The training preflight now records both total and
currently available system/GPU memory and refuses to start unless it sees at
least 8 GiB GPU memory available, 16 GiB total RAM, 8 GiB available RAM and
30 GiB free disk. It therefore correctly refuses on this machine before
loading weights. These thresholds are conservative guards, not a peak-memory
proof. GPU telemetry timeouts or malformed output and disk-capacity read errors
fail closed before model loading; mocked regression tests cover those cases.
The pinned
bitsandbytes QLoRA environment targets Linux/WSL; the application workspace
is native Windows.

At the start of the investigation, local Ollama 0.40.6 was reachable at
loopback and the already installed `qwen3:0.6b` quantized model was listed by
`/api/tags`. A bounded
GPU inference request failed at model load: `cudaMalloc failed: out of
memory`, attempting a 429,173,760-byte CUDA buffer. A second CPU-only request
(`num_gpu=0`, 512-token context, 32-token output) failed with Windows status
`0xc0000409` while allocating a 310,250,496-byte CPU buffer. No response was
generated. System telemetry at the later preflight showed only 1.37 GiB
available RAM, which is consistent with insufficient headroom, though it
does not prove the precise cause of the native runtime crash. The application
process currently has no model selected, so `/api/v1/model/status` correctly
reports `DISABLED`; when configured, the endpoint now distinguishes Ollama
service reachability, exact model installation and “installed but inference
not yet tested.” No Qwen3-4B/8B weights were downloaded, no inference quality
score was produced, and no training run was executed. After those inference
attempts the Ollama API stopped responding; a later `ollama ps` invocation
could not manage its service because the environment denied access to Ollama
log files. A fresh read-only probe on 2026-10-21 now reaches the loopback
service and finds `qwen3:0.6b` installed, reporting
`MODEL_INSTALLED_NOT_INFERRED`. The application model setting remains unset,
so the application continues to use deterministic behavior. This probe did
not run inference; the earlier runtime failures remain the only inference
evidence.

## Dataset and curation

Existing `data/learning` remains the deterministic spur-gear extraction
dataset with provenance and held-out evaluation. The new
`data/learning/engineering-v2` contains eight synthetic fixtures across
requirement extraction, constraints, assembly planning, tool proposals,
component understanding, change impact, failure handling, and engineering
explanation. It has four training, two validation, and two held-out examples;
the manifest marks it as a development fixture, not a specialist training
corpus or statistically meaningful benchmark. Validation checks provenance,
license, review status, category, dataset version, and split ID disjointness,
and produces split hashes.

Training capture is disabled by default. The local operator must set
`AEROPKMECH_ENABLE_TRAINING_CAPTURE=true` and each request must include
`opt_in: true`. Inputs and tool outputs are redacted for common secret/token
patterns and email addresses. Captures go to ignored `raw-traces/` and begin
as `UNREVIEWED`; a separate review call records an approval decision. Curation
then requires an approved trace, an explicit human-reviewed flag, reviewer
label, source license, task category, and structured expected output. Deletion
moves records to ignored quarantine storage. No private reasoning or
chain-of-thought is collected. This local-development boundary is not
multi-user identity or audit security. Curated records are a review queue, not
automatically inserted into a training split.

## Isolated training, evaluation, and promotion

`ml-training/` is separate from the API package and pins direct versions for
PyTorch, Transformers, TRL, PEFT, Accelerate, and Linux bitsandbytes. The
preflight refuses low VRAM/RAM/disk before any weight load. The config pins a
base-model revision, dataset version, seed, NF4 QLoRA settings, rank, steps,
and output directory. Large weights and adapters are ignored by Git. The
runner saves adapter/run metadata and does not promote an adapter.

The paired evaluator runs an unchanged base and candidate on the same held-out
records, records immutable model/dataset references, and reports JSON validity
plus exact expected-field subset accuracy. Thresholds are versioned in
`evaluation-thresholds.json`; the current threshold requires valid JSON and
candidate accuracy at least equal to base, with manual approval required.
The two-record test split is a smoke fixture only. The existing deterministic
gear evaluation remains separate and is the only measured baseline currently
available. No candidate-vs-base run or trained adapter exists.

The local `data/models/registry.json` records base revision, runtime model,
dataset/config/adapter checksums, evaluation suite, metrics, environment,
decision history, activation and rollback target. Lifecycle transitions are
enforced; activation requires metrics and an approval decision, and rollback
restores the previous approved runtime model. Runtime inference selects the
registry's active model first, then the explicit environment-configured local
baseline. Training never activates a model automatically.

## Commands and status

See [`../ml-training/README.md`](../ml-training/README.md) for isolated
environment setup and exact preflight, training, dataset validation, and paired
evaluation commands. Current state:

- Deterministic gear and EV proposal workflows: implemented.
- Local Ollama provider and component-grounded Q&A: implemented, but the
  available 0.6B model is installed; GPU inference failed from CUDA OOM
  and CPU inference failed with a native runtime crash; successful inference
  remains blocked. Status now distinguishes an unreachable service, an
  uninstalled model and an installed model that has not passed inference.
- Training capture/review/curation boundary: implemented and opt-in.
- Versioned dataset fixtures, provenance checks, split validation and hashes:
  implemented; the dataset is too small for useful fine-tuning.
- QLoRA environment/config/runner, evaluation harness and lifecycle registry:
  implemented but not executed end-to-end.
- Successful fine-tuning, candidate metrics, and model promotion: **not done**.
- Multi-user access control, independent ML benchmark, and production-sized
  reviewed corpus: **not implemented**.
