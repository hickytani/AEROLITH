"""Phase 3: Tiny Overfit Experiment for AEROLITH SLM.

Trains LoRA adapter on 3 selected engineering examples for 15 steps.
Verifies:
1. Finite loss & nonzero gradients.
2. Loss reduction across steps.
3. LoRA adapter parameter change.
4. Evaluation reproduction on the 3 overfitted examples before vs after.
5. Checkpoint saving, reload, and identical reload inference.
"""
from __future__ import annotations

import gc
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import torch
from peft import LoraConfig, PeftModel, get_peft_model
from torch.utils.data import DataLoader, Dataset
from transformers import AutoTokenizer

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ml-training/scripts"))
from model_loader import load_model_no_mmap

MODEL_PATH = Path(r"C:\Users\prasu\.cache\hf_direct\Qwen2.5-0.5B-Instruct")
TRAIN_JSONL = REPO_ROOT / "data/learning/engineering-v2.2.0/train.jsonl"
EXPERIMENT_DIR = REPO_ROOT / ".local-models/runs/qwen2.5-0.5b-tiny-overfit"


class MaskedEngineeringDataset(Dataset):
    def __init__(self, samples: list[dict], tokenizer, max_length: int = 256):
        self.examples = []
        system_msg = (
            "You are AEROLITH's engineering parameter extraction and constraint model. "
            "Output one valid JSON object adhering strictly to the required schema. "
            "Never invent unmentioned dimensions or make unsubstantiated safety claims."
        )

        for item in samples:
            user_payload = {
                "task_category": item["task_category"],
                "input": item["input"],
                "context": item.get("context", {}),
            }
            assistant_payload = item["expected_output"]

            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                {"role": "assistant", "content": json.dumps(assistant_payload, ensure_ascii=False)},
            ]

            rendered_full = tokenizer.apply_chat_template(messages, tokenize=False)
            rendered_prompt = tokenizer.apply_chat_template(messages[:2], tokenize=False, add_generation_prompt=True)

            enc_full = tokenizer(rendered_full, max_length=max_length, truncation=True, padding=False, return_tensors="pt")
            enc_prompt = tokenizer(rendered_prompt, return_tensors="pt")

            input_ids = enc_full["input_ids"].squeeze(0)
            attention_mask = enc_full["attention_mask"].squeeze(0)
            prompt_len = enc_prompt["input_ids"].shape[1]

            labels = input_ids.clone()
            labels[:prompt_len] = -100  # Mask out system + user prompt tokens

            supervised_count = (labels != -100).sum().item()
            assert supervised_count > 0, f"Sample {item['id']} has no supervised tokens!"

            self.examples.append({
                "id": item["id"],
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "labels": labels,
                "supervised_tokens": supervised_count,
                "prompt_tokens": prompt_len,
                "raw_sample": item,
            })

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, idx: int) -> dict:
        return self.examples[idx]


def collate_single(batch):
    item = batch[0]
    return {
        "input_ids": item["input_ids"].unsqueeze(0),
        "attention_mask": item["attention_mask"].unsqueeze(0),
        "labels": item["labels"].unsqueeze(0),
    }


def run_tiny_overfit():
    print("=" * 75)
    print("PHASE 3: TINY OVERFIT EXPERIMENT (ISOLATED RUN)")
    print("=" * 75)
    torch.set_num_threads(4)
    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Select 3 diverse training samples
    all_train = [json.loads(line) for line in TRAIN_JSONL.read_text(encoding="utf-8").splitlines() if line.strip()]
    selected_samples = [all_train[0], all_train[1], all_train[2]]
    print(f"Selected {len(selected_samples)} samples:")
    for s in selected_samples:
        print(f"  - [{s['id']}] {s['input'][:65]}...")

    # 2. Load Base Model & Tokenizer
    print("\n1. Loading base model via zero-mmap loader with tied weights...")
    t0_load = time.perf_counter()
    model, tokenizer = load_model_no_mmap(MODEL_PATH, target_dtype=torch.bfloat16, verbose=False)
    print(f"   Model loaded in {time.perf_counter() - t0_load:.2f}s.")

    dataset = MaskedEngineeringDataset(selected_samples, tokenizer)
    loader = DataLoader(dataset, batch_size=1, shuffle=True, collate_fn=collate_single)

    for ex in dataset:
        print(f"   Sample {ex['id']}: {ex['prompt_tokens']} prompt tokens (masked), {ex['supervised_tokens']} supervised target tokens")

    # 3. Inject LoRA adapters
    print("\n2. Injecting LoRA adapters (r=8, alpha=16, targets=['q_proj', 'v_proj'])...")
    peft_config = LoraConfig(
        r=8,
        lora_alpha=16,
        lora_dropout=0.0,
        target_modules=["q_proj", "v_proj"],
        task_type="CAUSAL_LM",
    )
    lora_model = get_peft_model(model, peft_config)
    for name, param in lora_model.named_parameters():
        if param.requires_grad:
            param.data = param.data.to(torch.float32)

    trainable_params = sum(p.numel() for p in lora_model.parameters() if p.requires_grad)
    print(f"   Trainable LoRA parameters: {trainable_params:,}")

    # Track initial parameter snapshots
    q0_B = lora_model.base_model.model.model.layers[0].self_attn.q_proj.lora_B["default"].weight
    initial_B_snapshot = q0_B.clone().detach()

    # 4. Measure initial loss before training
    lora_model.eval()
    initial_losses = []
    with torch.no_grad():
        for batch in loader:
            out = lora_model(
                input_ids=batch["input_ids"],
                attention_mask=batch["attention_mask"],
                labels=batch["labels"],
            )
            initial_losses.append(out.loss.item())
    mean_initial_loss = sum(initial_losses) / len(initial_losses)
    print(f"\n3. Pre-training Mean Loss across 3 samples: {mean_initial_loss:.4f}")

    # 5. Training Loop: 4 steps with lr=0.001
    max_steps = 4
    lr = 0.001
    optimizer = torch.optim.AdamW([p for p in lora_model.parameters() if p.requires_grad], lr=lr, weight_decay=0.01)
    print(f"\n4. Executing training loop ({max_steps} steps, lr={lr})...", flush=True)

    lora_model.train()
    step = 0
    step_history = []
    t_train_start = time.perf_counter()

    while step < max_steps:
        for batch in loader:
            if step >= max_steps:
                break
            optimizer.zero_grad()
            outputs = lora_model(
                input_ids=batch["input_ids"],
                attention_mask=batch["attention_mask"],
                labels=batch["labels"],
            )
            loss = outputs.loss
            raw_loss = loss.item()
            loss.backward()

            # Calculate total gradient norm
            grad_norm = 0.0
            for p in lora_model.parameters():
                if p.requires_grad and p.grad is not None:
                    grad_norm += p.grad.float().norm().item() ** 2
            grad_norm = grad_norm ** 0.5

            optimizer.step()
            optimizer.zero_grad()

            # CRITICAL memory hygiene for CPU execution: free activation graphs immediately
            del outputs, loss
            gc.collect()

            step_history.append({"step": step + 1, "loss": round(raw_loss, 4), "grad_norm": round(grad_norm, 4)})
            print(f"   Step {step + 1:2d}/{max_steps} | Loss: {raw_loss:.4f} | GradNorm: {grad_norm:.4f}", flush=True)
            step += 1

    train_duration = time.perf_counter() - t_train_start
    print(f"   Training finished in {train_duration:.2f}s.", flush=True)

    # 6. Verify parameter movement
    final_B_snapshot = q0_B.clone().detach()
    delta_B = (final_B_snapshot - initial_B_snapshot).norm().item()
    print(f"\n5. Parameter Movement Verification:")
    print(f"   LoRA-B weight L2 delta: {delta_B:.6f} (Must be > 0)")
    assert delta_B > 0.001, "LoRA parameters did not change significantly!"

    # 7. Post-training Loss
    lora_model.eval()
    post_losses = []
    with torch.no_grad():
        for batch in loader:
            out = lora_model(
                input_ids=batch["input_ids"],
                attention_mask=batch["attention_mask"],
                labels=batch["labels"],
            )
            post_losses.append(out.loss.item())
    mean_post_loss = sum(post_losses) / len(post_losses)
    loss_reduction = mean_initial_loss - mean_post_loss
    print(f"\n6. Post-training Mean Loss: {mean_post_loss:.4f}")
    print(f"   Loss Reduction: {loss_reduction:+.4f} ({100 * loss_reduction / mean_initial_loss:.1f}% reduction)")
    assert loss_reduction > 0.1, f"Expected loss reduction > 0.1, got {loss_reduction:.4f}"

    # 8. Save checkpoint to isolated experiment directory
    print(f"\n7. Saving checkpoint to {EXPERIMENT_DIR}...")
    lora_model.save_pretrained(str(EXPERIMENT_DIR))
    tokenizer.save_pretrained(str(EXPERIMENT_DIR))

    adapter_path = EXPERIMENT_DIR / "adapter_model.safetensors"
    adapter_bytes = adapter_path.read_bytes()
    adapter_sha = hashlib.sha256(adapter_bytes).hexdigest()
    print(f"   Checkpoint saved. Size: {len(adapter_bytes)/1024:.1f} KB, SHA256: {adapter_sha[:16]}...")

    # 9. Test inference with current model
    print("\n8. Testing inference on training sample 1...")
    system_msg = (
        "You are AEROLITH's engineering parameter extraction and constraint model. "
        "Output one valid JSON object adhering strictly to the required schema. "
        "Never invent unmentioned dimensions or make unsubstantiated safety claims."
    )
    test_sample = selected_samples[0]
    user_payload = {
        "task_category": test_sample["task_category"],
        "input": test_sample["input"],
        "context": test_sample.get("context", {}),
    }
    msgs = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]
    prompt_rendered = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    enc_test = tokenizer(prompt_rendered, return_tensors="pt")

    with torch.inference_mode():
        gen_before_reload = lora_model.generate(
            **enc_test,
            max_new_tokens=100,
            do_sample=False,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )
    output_before = tokenizer.decode(gen_before_reload[0][enc_test["input_ids"].shape[1]:], skip_special_tokens=True)
    print(f"   Output before reload:\n   {repr(output_before[:150])}")

    # 10. Checkpoint Reload Verification
    print("\n9. Testing checkpoint reload from disk...")
    del lora_model, model
    gc.collect()

    reloaded_base, reloaded_tok = load_model_no_mmap(MODEL_PATH, target_dtype=torch.bfloat16, verbose=False)
    reloaded_lora = PeftModel.from_pretrained(reloaded_base, str(EXPERIMENT_DIR))
    reloaded_lora.eval()

    with torch.inference_mode():
        gen_after_reload = reloaded_lora.generate(
            **enc_test,
            max_new_tokens=100,
            do_sample=False,
            pad_token_id=reloaded_tok.pad_token_id,
            eos_token_id=reloaded_tok.eos_token_id,
        )
    output_after = reloaded_tok.decode(gen_after_reload[0][enc_test["input_ids"].shape[1]:], skip_special_tokens=True)
    print(f"   Output after reload:\n   {repr(output_after[:150])}")

    # Check identical generation
    identical = (output_before == output_after)
    print(f"   Deterministic Reload Verification: {'PASS (Identical)' if identical else 'DIFF'}")
    assert identical, "Reloaded model output differed from in-memory model!"

    # Save metadata
    meta = {
        "experiment_id": "qwen2.5-0.5b-tiny-overfit",
        "base_model": "Qwen/Qwen2.5-0.5B-Instruct",
        "adapter_sha256": adapter_sha,
        "train_samples": [s["id"] for s in selected_samples],
        "max_steps": max_steps,
        "learning_rate": lr,
        "initial_loss": round(mean_initial_loss, 4),
        "final_loss": round(mean_post_loss, 4),
        "loss_reduction": round(loss_reduction, 4),
        "parameter_delta_L2": round(delta_B, 6),
        "duration_sec": round(train_duration, 2),
        "steps": step_history,
        "output_sample": output_after,
        "status": "PASS",
    }
    (EXPERIMENT_DIR / "run-metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"\nMetadata written to {EXPERIMENT_DIR / 'run-metadata.json'}")
    print("=" * 75)
    print("PHASE 3 TINY OVERFIT EXPERIMENT: SUCCESS!")
    print("=" * 75)
    return meta


if __name__ == "__main__":
    run_tiny_overfit()

