"""Smoke test: LoRA forward, backward, save, reload on Qwen2.5-0.5B.

Uses the zero-allocation mmap-free loader. Set LOCAL_MODEL_PATH env var.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import torch
from peft import LoraConfig, PeftModel, get_peft_model

_LOCAL = os.environ.get("LOCAL_MODEL_PATH", "").strip() or (sys.argv[1] if len(sys.argv) > 1 else "")
if not _LOCAL:
    print("ERROR: Set LOCAL_MODEL_PATH env var.", file=sys.stderr); sys.exit(1)

MODEL_DIR    = Path(_LOCAL)
SMOKE_OUTPUT = Path(".local-models/smoke-lora-test")

sys.path.insert(0, str(Path(__file__).parent))
from model_loader import load_model_no_mmap


def main() -> int:
    print(f"=== AEROLITH LoRA Smoke Test ===")
    print(f"Model dir : {MODEL_DIR}")

    # 1. Load base model
    print("\n[1] Loading base model (zero-alloc, no mmap)...")
    t0 = time.perf_counter()
    model, tokenizer = load_model_no_mmap(MODEL_DIR, target_dtype=torch.bfloat16)
    load_time = time.perf_counter() - t0
    total_params = sum(p.numel() for p in model.parameters())
    print(f"    Loaded {total_params/1e6:.1f}M params in {load_time:.1f}s")

    # 2. Apply LoRA
    print("\n[2] Applying LoRA...")
    lora_config = LoraConfig(r=8, lora_alpha=16, lora_dropout=0.05,
                             target_modules=["q_proj", "v_proj"], task_type="CAUSAL_LM")
    lora_model = get_peft_model(model, lora_config)
    # Cast LoRA adapter weights to float32 for stable CPU backward
    for name, param in lora_model.named_parameters():
        if param.requires_grad:
            param.data = param.data.to(torch.float32)
    trainable = sum(p.numel() for p in lora_model.parameters() if p.requires_grad)
    print(f"    Trainable LoRA params: {trainable:,} ({100*trainable/total_params:.3f}%)")

    # 3. Forward + backward
    print("\n[3] Forward + backward...")
    inputs = tokenizer("Spur gear: 18 teeth, module 2 mm.", return_tensors="pt")
    inputs["labels"] = inputs["input_ids"].clone()
    outputs = lora_model(**inputs)
    loss = outputs.loss
    print(f"    Loss: {loss.item():.4f}")
    loss.backward()
    print("    Backward: OK")

    # 4. Save
    print(f"\n[4] Saving checkpoint to {SMOKE_OUTPUT}...")
    SMOKE_OUTPUT.mkdir(parents=True, exist_ok=True)
    lora_model.save_pretrained(str(SMOKE_OUTPUT))
    tokenizer.save_pretrained(str(SMOKE_OUTPUT))
    print(f"    Files: {[p.name for p in SMOKE_OUTPUT.iterdir()]}")

    # 5. Reload
    print(f"\n[5] Reloading and testing inference...")
    del lora_model, model; import gc; gc.collect()
    base2, _ = load_model_no_mmap(MODEL_DIR, target_dtype=torch.bfloat16, verbose=False)
    reloaded = PeftModel.from_pretrained(base2, str(SMOKE_OUTPUT))
    reloaded.eval()
    with torch.no_grad():
        gen = reloaded.generate(**inputs, max_new_tokens=20, do_sample=False)
    decoded = tokenizer.decode(gen[0], skip_special_tokens=True)
    print(f"    Output: {decoded[:200]}")

    print("\n✓ SMOKE TEST PASSED")
    return 0

if __name__ == "__main__":
    sys.exit(main())
