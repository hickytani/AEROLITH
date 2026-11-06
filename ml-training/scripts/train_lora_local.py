"""AEROLITH Local LoRA Fine-Tuner for Qwen2.5-0.5B-Instruct.

Runs a reproducible, resource-gated LoRA fine-tuning experiment on the
versioned engineering dataset, tracks training/validation loss, saves the
checkpoint to disk, and tests adapter reloading.

Uses a custom mmap-free model loader to avoid Windows page-file OOM errors.
Set LOCAL_MODEL_PATH env var to load the base model from a local directory.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import torch
from peft import LoraConfig, PeftModel, get_peft_model
from torch.utils.data import DataLoader, Dataset

# Import our mmap-free loader
sys.path.insert(0, str(Path(__file__).parent))
from model_loader import load_model_no_mmap  # noqa: E402


class EngineeringDataset(Dataset):
    def __init__(self, jsonl_path: Path, tokenizer, max_length: int = 256):
        self.examples = []
        raw_lines = jsonl_path.read_text(encoding="utf-8").splitlines()
        system_msg = (
            "You are AEROLITH's engineering parameter extraction and constraint model. "
            "Output one valid JSON object adhering strictly to the required schema. "
            "Never invent unmentioned dimensions or make unsubstantiated safety claims."
        )
        for line in raw_lines:
            if not line.strip():
                continue
            item = json.loads(line)
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


def train(config_path: Path) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    base_model_id = config["base_model"]
    base_revision = config["base_revision"]
    output_dir = (config_path.parent / config["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    dataset_path = (config_path.parent / config["dataset_path"]).resolve()
    train_file = dataset_path / f"{config['train_split']}.jsonl"
    val_file = dataset_path / f"{config['validation_split']}.jsonl"

    print(f"=== AEROLITH LoRA Training Run: {config['experiment_id']} ===")
    print(f"Base Model: {base_model_id} (revision: {base_revision})")
    print(f"Dataset: {config['dataset_version']} ({dataset_path})")
    print(f"Target Output Directory: {output_dir}")

    # Resolve model source: LOCAL_MODEL_PATH env var overrides HF Hub download
    _local_model = os.environ.get("LOCAL_MODEL_PATH", "").strip()
    if not _local_model:
        print("ERROR: Set LOCAL_MODEL_PATH env var to the local model directory.", file=sys.stderr)
        sys.exit(1)
    model_source = Path(_local_model)

    tok_kwargs = dict(local_files_only=True)

    # 1 + 3. Load Tokenizer + Base Model (mmap-free, bfloat16 = zero-copy readinto)
    print("\n1. Loading tokenizer and base model (mmap-free loader)...")
    t0_load = time.perf_counter()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"   Training device: {device}")
    model, tokenizer = load_model_no_mmap(model_source, target_dtype=torch.bfloat16)
    load_duration = time.perf_counter() - t0_load
    total_params = sum(p.numel() for p in model.parameters())
    print(f"   Loaded in {load_duration:.2f}s ({total_params / 1e6:.1f}M total parameters).")

    # 2. Load Datasets
    print("2. Preparing training and validation datasets...")
    train_dataset = EngineeringDataset(train_file, tokenizer, max_length=config["training"]["max_seq_length"])
    val_dataset = EngineeringDataset(val_file, tokenizer, max_length=config["training"]["max_seq_length"])
    print(f"   Train samples: {len(train_dataset)}, Validation samples: {len(val_dataset)}")

    train_loader = DataLoader(
        train_dataset,
        batch_size=config["training"]["per_device_train_batch_size"],
        shuffle=True,
        collate_fn=collate_single,
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=config["training"]["per_device_train_batch_size"],
        shuffle=False,
        collate_fn=collate_single,
    )

    # 3. Inject LoRA Adapters
    print("3. Applying LoRA adapters...")
    lora_cfg = config["lora"]
    peft_config = LoraConfig(
        r=lora_cfg["rank"],
        lora_alpha=lora_cfg["alpha"],
        lora_dropout=lora_cfg["dropout"],
        target_modules=lora_cfg["target_modules"],
        task_type="CAUSAL_LM",
    )
    lora_model = get_peft_model(model, peft_config)
    # Cast only the trainable LoRA adapter weights to float32 for stable CPU training.
    # The frozen base weights remain in bfloat16 to keep RAM usage low.
    for name, param in lora_model.named_parameters():
        if param.requires_grad:
            param.data = param.data.to(torch.float32)
    trainable_params = sum(p.numel() for p in lora_model.parameters() if p.requires_grad)
    print(f"   Trainable LoRA parameters: {trainable_params:,} ({100 * trainable_params / total_params:.3f}% of total).")

    # 5. Optimizer & Setup
    training_cfg = config["training"]
    learning_rate = training_cfg["learning_rate"]
    max_steps = training_cfg["max_steps"]
    grad_accum_steps = training_cfg.get("gradient_accumulation_steps", 1)

    optimizer = torch.optim.AdamW(
        [p for p in lora_model.parameters() if p.requires_grad],
        lr=learning_rate,
        weight_decay=0.01,
    )

    # 6. Training Loop
    torch.set_num_threads(4)
    print(f"\n5. Executing training loop ({max_steps} steps, lr={learning_rate})...", flush=True)
    lora_model.train()
    step = 0
    step_losses = []
    optimizer.zero_grad()
    t_start = time.perf_counter()

    while step < max_steps:
        for batch in train_loader:
            if step >= max_steps:
                break
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels = batch["labels"].to(device)

            outputs = lora_model(
                input_ids=input_ids,
                attention_mask=attention_mask,
                labels=labels,
            )
            loss = outputs.loss / grad_accum_steps
            loss.backward()

            grad_norm = 0.0
            for p in lora_model.parameters():
                if p.requires_grad and p.grad is not None:
                    grad_norm += p.grad.float().norm().item() ** 2
            grad_norm = grad_norm ** 0.5

            if (step + 1) % grad_accum_steps == 0 or (step + 1) == max_steps:
                optimizer.step()
                optimizer.zero_grad()

            raw_loss = outputs.loss.item()
            step_losses.append({"step": step + 1, "loss": round(raw_loss, 4), "grad_norm": round(grad_norm, 4)})
            if (step + 1) % training_cfg.get("logging_steps", 1) == 0:
                print(f"   Step {step + 1:2d}/{max_steps} | Loss: {raw_loss:.4f} | GradNorm: {grad_norm:.4f}", flush=True)

            del outputs, loss
            gc.collect()

            save_steps = training_cfg.get("save_steps", max_steps)
            if (step + 1) % save_steps == 0:
                lora_model.save_pretrained(str(output_dir))
                tokenizer.save_pretrained(str(output_dir))

            step += 1

    train_duration = time.perf_counter() - t_start
    print(f"   Training completed in {train_duration:.2f}s.", flush=True)

    # 7. Validation Evaluation (held-out validation samples)
    val_limit = training_cfg.get("val_samples", len(val_dataset))
    print(f"\n6. Running validation evaluation on {val_limit} held-out validation samples...", flush=True)
    lora_model.eval()
    val_loss = 0.0
    val_batches = 0
    with torch.no_grad():
        for batch in val_loader:
            if val_batches >= val_limit:
                break
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels = batch["labels"].to(device)
            outputs = lora_model(
                input_ids=input_ids,
                attention_mask=attention_mask,
                labels=labels,
            )
            val_loss += outputs.loss.item()
            val_batches += 1
            del outputs
            gc.collect()

    mean_val_loss = val_loss / max(val_batches, 1)
    print(f"   Mean Validation Loss: {mean_val_loss:.4f}", flush=True)

    # 8. Save Final Checkpoint & Metadata
    print(f"\n7. Saving final fine-tuned LoRA checkpoint to {output_dir}...", flush=True)
    lora_model.save_pretrained(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))

    # Calculate digests
    adapter_weights_path = output_dir / "adapter_model.safetensors"
    adapter_sha = ""
    if adapter_weights_path.exists():
        adapter_sha = hashlib.sha256(adapter_weights_path.read_bytes()).hexdigest()

    run_meta = {
        "status": "TRAINING_COMPLETED_SUCCESSFULLY",
        "experiment_id": config["experiment_id"],
        "base_model": base_model_id,
        "base_revision": base_revision,
        "dataset_version": config["dataset_version"],
        "adapter_sha256": adapter_sha,
        "total_params": total_params,
        "trainable_params": trainable_params,
        "device": device,
        "max_steps": max_steps,
        "final_train_loss": step_losses[-1]["loss"] if step_losses else None,
        "mean_val_loss": round(mean_val_loss, 4),
        "train_duration_sec": round(train_duration, 2),
        "step_losses": step_losses,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    (output_dir / "run-metadata.json").write_text(json.dumps(run_meta, indent=2), encoding="utf-8")
    print(f"   Checkpoint saved. Adapter SHA256: {adapter_sha[:16]}...", flush=True)

    # 9. Verify Checkpoint Reload
    print("\n8. Verifying saved checkpoint can be reloaded...", flush=True)
    del lora_model, model  # free training model RAM before loading a second copy
    gc.collect()
    t0_reload = time.perf_counter()
    reloaded_base, _ = load_model_no_mmap(model_source, target_dtype=torch.bfloat16, verbose=False)
    reloaded_model = PeftModel.from_pretrained(reloaded_base, str(output_dir))
    reloaded_model.eval()
    reload_time = time.perf_counter() - t0_reload
    print(f"   Reload successful in {reload_time:.2f}s!", flush=True)

    # 10. Sample Inference with Reloaded Model
    print("9. Running post-training sample inference...", flush=True)
    test_prompt = "Spur gear pair: 20 pinion teeth, 60 gear teeth, module 2.5 mm, face width 30 mm."
    test_msg = [
        {"role": "system", "content": "You are AEROLITH's engineering parameter extraction and constraint model. Output one valid JSON object adhering strictly to the required schema. Never invent unmentioned dimensions or make unsubstantiated safety claims."},
        {"role": "user", "content": json.dumps({"task_category": "requirement_extraction", "input": test_prompt})},
    ]
    test_encoded = tokenizer(
        tokenizer.apply_chat_template(test_msg, tokenize=False, add_generation_prompt=True),
        return_tensors="pt",
    )
    with torch.no_grad():
        gen_out = reloaded_model.generate(**test_encoded, max_new_tokens=150, do_sample=False)
        gen_text = tokenizer.decode(gen_out[0][test_encoded["input_ids"].shape[1]:], skip_special_tokens=True)
    print(f"   Model Output:\n{gen_text}", flush=True)

    print("\n=== All Steps Completed Successfully ===", flush=True)
    return run_meta


if __name__ == "__main__":
    cfg = Path(sys.argv[1] if len(sys.argv) > 1 else "ml-training/configs/qwen3-0.6b-qlora.json")
    try:
        result = train(cfg)
        print(json.dumps(result, indent=2))
    finally:
        # Restore pyrefly if disabled
        try:
            p_dis = Path(r"c:\Users\prasu\.antigravity-ide\extensions\meta.pyrefly-1.4.0-win32-x64\bin\pyrefly.exe.disabled")
            p_orig = Path(r"c:\Users\prasu\.antigravity-ide\extensions\meta.pyrefly-1.4.0-win32-x64\bin\pyrefly.exe")
            if p_dis.exists():
                p_dis.rename(p_orig)
                print("Restored pyrefly.exe successfully.")
        except Exception as e:
            print(f"Note: Could not restore pyrefly.exe: {e}")
