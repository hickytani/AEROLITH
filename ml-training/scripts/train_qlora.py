"""QLoRA runner, intentionally gated by immutable model revision and preflight."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from preflight import check_hardware
from validate_dataset import validate


def run(config_path: Path) -> None:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not re.fullmatch(r"[0-9a-f]{40}", str(config.get("base_revision", ""))):
        raise ValueError("Pin a verified 40-character immutable Hugging Face commit SHA before training.")
    dataset = (config_path.parent / config["dataset_path"]).resolve()
    dataset_report = validate(dataset)
    if dataset_report["dataset_version"] != config["dataset_version"]:
        raise ValueError("Configured dataset version does not match its manifest.")
    hardware = check_hardware()
    print(json.dumps(hardware, indent=2))
    if not hardware["ready"]:
        raise RuntimeError("Hardware preflight failed; no model was downloaded and no training was started.")
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TrainingArguments
        from trl import SFTTrainer
    except ImportError as exc:
        raise RuntimeError("Isolated training dependencies are missing; install ml-training/ separately.") from exc
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError("This pinned experiment requires a CUDA GPU with BF16 support; select a separately evaluated compatible config.")
    base = config["base_model"]
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(base, revision=config["base_revision"], quantization_config=quant, device_map="auto")
    tokenizer = AutoTokenizer.from_pretrained(base, revision=config["base_revision"])
    data = []
    for line in (dataset / "train.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            data.append({"text": json.dumps({"input": item.get("input", item.get("text")), "expected": item.get("expected_output", item.get("expected"))}, ensure_ascii=False)})
    training = config["training"]
    args = TrainingArguments(output_dir=config["output_dir"], max_steps=training["max_steps"], learning_rate=training["learning_rate"],
        per_device_train_batch_size=training["per_device_train_batch_size"], gradient_accumulation_steps=training["gradient_accumulation_steps"],
        logging_steps=training["logging_steps"], save_steps=training["save_steps"], seed=training["seed"], report_to=[],
        gradient_checkpointing=True, bf16=True, optim="paged_adamw_8bit")
    trainer = SFTTrainer(model=model, tokenizer=tokenizer, train_dataset=Dataset.from_list(data), peft_config=LoraConfig(
        r=config["lora"]["rank"], lora_alpha=config["lora"]["alpha"], lora_dropout=config["lora"]["dropout"],
        target_modules=config["lora"]["target_modules"], task_type="CAUSAL_LM"), args=args, max_seq_length=training["max_seq_length"])
    started = datetime.now(timezone.utc).isoformat()
    trainer.train(resume_from_checkpoint=True if Path(config["output_dir"]).exists() else None)
    trainer.save_model(config["output_dir"])
    metadata = {"status": "TRAINING_COMPLETED_EVALUATION_REQUIRED", "base_model": base, "base_revision": config["base_revision"],
        "dataset": dataset_report, "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(), "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(), "seed": training["seed"], "metrics": trainer.state.log_history, "hardware": hardware,
        "promotion": "NOT_PROMOTED"}
    Path(config["output_dir"], "run-metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    try:
        run(Path(sys.argv[1]))
    except Exception as exc:
        print(json.dumps({"status": "FAILED_OR_NOT_STARTED", "error": str(exc), "model_promoted": False}, indent=2))
        raise SystemExit(2)
