"""Diagnostic script for Phase 2: Diagnose the constant loss in AEROLITH LoRA pipeline.

Tests:
1. Tokenizer & chat template formatting (input_ids, attention_mask, prompt vs assistant tokens)
2. Label construction and masking (-100 positions, target token count)
3. Model logits (finiteness, uniformity, top-k tokens)
4. Loss computation (raw cross-entropy, causal LM shift, unmasked vs masked)
5. Gradient flow (LoRA A grad, LoRA B grad, grad norms)
6. Optimizer step behavior (parameter delta, before vs after step)
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoTokenizer

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ml-training/scripts"))
from model_loader import load_model_no_mmap

MODEL_PATH = Path(r"C:\Users\prasu\.cache\hf_direct\Qwen2.5-0.5B-Instruct")
TRAIN_JSONL = REPO_ROOT / "data/learning/engineering-v2.2.0/train.jsonl"


def run_diagnostics():
    print("=" * 70)
    print("PHASE 2 DIAGNOSTICS: ROOT CAUSE ANALYSIS OF CONSTANT LOSS")
    print("=" * 70, flush=True)

    # 1. Load 1 sample from train.jsonl
    with open(TRAIN_JSONL, "r", encoding="utf-8") as f:
        first_line = f.readline()
    sample = json.loads(first_line)
    print(f"\n[1] Sample loaded: {sample['id']} ({sample['task_category']})")
    print(f"    Input: {sample['input']}")
    print(f"    Target: {sample['expected_output']}")

    # 2. Tokenizer & Chat Template
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_PATH), local_files_only=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    print(f"\n[2] Tokenizer: vocab_size={tokenizer.vocab_size}, pad_token_id={tokenizer.pad_token_id}, eos_token_id={tokenizer.eos_token_id}")

    system_msg = (
        "You are AEROLITH's engineering parameter extraction and constraint model. "
        "Output one valid JSON object adhering strictly to the required schema. "
        "Never invent unmentioned dimensions or make unsubstantiated safety claims."
    )
    user_payload = {
        "task_category": sample["task_category"],
        "input": sample["input"],
        "context": sample.get("context", {}),
    }
    assistant_payload = sample["expected_output"]

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        {"role": "assistant", "content": json.dumps(assistant_payload, ensure_ascii=False)},
    ]

    rendered_full = tokenizer.apply_chat_template(messages, tokenize=False)
    print(f"\n[3] Rendered Chat Template (first 250 chars):\n{repr(rendered_full[:250])}")
    print(f"    Rendered Chat Template (last 150 chars):\n{repr(rendered_full[-150:])}")

    # Inspect tokenization of prompt vs assistant
    prompt_messages = messages[:2]
    rendered_prompt = tokenizer.apply_chat_template(prompt_messages, tokenize=False, add_generation_prompt=True)
    
    enc_full = tokenizer(rendered_full, return_tensors="pt")
    enc_prompt = tokenizer(rendered_prompt, return_tensors="pt")

    full_ids = enc_full["input_ids"][0]
    prompt_ids = enc_prompt["input_ids"][0]
    
    print(f"\n[4] Token Counts:")
    print(f"    Full sequence length  : {len(full_ids)} tokens")
    print(f"    Prompt sequence length: {len(prompt_ids)} tokens")
    print(f"    Assistant tokens      : {len(full_ids) - len(prompt_ids)} tokens")

    # In existing train_lora_local.py:
    # labels = input_ids.clone() -> NO MASKING of prompt tokens!
    existing_labels = full_ids.clone()
    num_supervised_existing = (existing_labels != -100).sum().item()
    print(f"\n[5] Existing Pipeline Label Strategy:")
    print(f"    Supervised tokens in existing code: {num_supervised_existing} (ALL tokens!)")
    print(f"    Ignored (-100) tokens in existing code: {(existing_labels == -100).sum().item()}")

    # Masked strategy:
    masked_labels = full_ids.clone()
    masked_labels[:len(prompt_ids)] = -100
    print(f"\n[6] Masked Label Strategy:")
    print(f"    Supervised tokens with masking: {(masked_labels != -100).sum().item()}")
    print(f"    Ignored (-100) tokens with masking: {(masked_labels == -100).sum().item()}")

    # 3. Model Loading & Weights Check
    print(f"\n[7] Loading base model via model_loader...")
    model, _ = load_model_no_mmap(MODEL_PATH, target_dtype=torch.bfloat16, verbose=False)
    model.eval()

    # Forward pass on base model
    with torch.no_grad():
        out_base = model(input_ids=full_ids.unsqueeze(0), attention_mask=enc_full["attention_mask"])
        logits_base = out_base.logits[0]  # shape: [seq_len, vocab_size]
    
    print(f"    Base logits shape: {logits_base.shape}")
    print(f"    Base logits finite: {torch.isfinite(logits_base).all().item()}")
    print(f"    Base logits mean: {logits_base.float().mean().item():.4f}, std: {logits_base.float().std().item():.4f}")
    print(f"    Base logits min: {logits_base.float().min().item():.4f}, max: {logits_base.float().max().item():.4f}")

    # Top-5 predicted tokens at end of prompt:
    prompt_last_idx = len(prompt_ids) - 1
    top5_at_prompt = torch.topk(logits_base[prompt_last_idx].float(), 5)
    top5_tokens = [tokenizer.decode([idx.item()]) for idx in top5_at_prompt.indices]
    print(f"    Top-5 tokens predicted after prompt: {top5_tokens}")

    # Compute loss under existing unmasked labels vs masked labels
    with torch.no_grad():
        out_unmasked = model(input_ids=full_ids.unsqueeze(0), attention_mask=enc_full["attention_mask"], labels=existing_labels.unsqueeze(0))
        loss_unmasked = out_unmasked.loss.item()
        
        out_masked = model(input_ids=full_ids.unsqueeze(0), attention_mask=enc_full["attention_mask"], labels=masked_labels.unsqueeze(0))
        loss_masked = out_masked.loss.item()
        
    print(f"\n[8] Base Model Initial Loss:")
    print(f"    Loss (Unmasked, existing code): {loss_unmasked:.4f}")
    print(f"    Loss (Masked prompt):           {loss_masked:.4f}")

    # 4. LoRA Setup and Gradient Flow
    peft_config = LoraConfig(
        r=8,
        lora_alpha=16,
        lora_dropout=0.0,  # 0 dropout for deterministic inspection
        target_modules=["q_proj", "v_proj"],
        task_type="CAUSAL_LM",
    )
    lora_model = get_peft_model(model, peft_config)
    lora_model.train()

    # Inspect LoRA weights dtypes & init
    q0_A = lora_model.base_model.model.model.layers[0].self_attn.q_proj.lora_A["default"].weight
    q0_B = lora_model.base_model.model.model.layers[0].self_attn.q_proj.lora_B["default"].weight
    print(f"\n[9] LoRA Initial Parameters:")
    print(f"    lora_A dtype: {q0_A.dtype}, norm: {q0_A.float().norm().item():.4f}")
    print(f"    lora_B dtype: {q0_B.dtype}, norm: {q0_B.float().norm().item():.4f} (expected 0.0)")

    # Test what train_lora_local.py did: casting trainable params to float32
    for name, param in lora_model.named_parameters():
        if param.requires_grad:
            param.data = param.data.to(torch.float32)

    optimizer = torch.optim.AdamW([p for p in lora_model.parameters() if p.requires_grad], lr=0.001)

    # Forward & backward with MASKED labels
    optimizer.zero_grad()
    out_train = lora_model(
        input_ids=full_ids.unsqueeze(0),
        attention_mask=enc_full["attention_mask"],
        labels=masked_labels.unsqueeze(0),
    )
    step0_loss = out_train.loss.item()
    out_train.loss.backward()

    # Check gradients
    grad_A = q0_A.grad
    grad_B = q0_B.grad
    print(f"\n[10] Gradients after backward pass:")
    print(f"    lora_A grad is None: {grad_A is None}")
    if grad_A is not None:
        print(f"    lora_A grad norm: {grad_A.float().norm().item():.6f}")
    print(f"    lora_B grad is None: {grad_B is None}")
    if grad_B is not None:
        print(f"    lora_B grad norm: {grad_B.float().norm().item():.6f}")

    # Total gradient norm across all LoRA parameters
    total_grad_norm = 0.0
    for p in lora_model.parameters():
        if p.requires_grad and p.grad is not None:
            total_grad_norm += p.grad.float().norm().item() ** 2
    total_grad_norm = total_grad_norm ** 0.5
    print(f"    Total LoRA gradient norm: {total_grad_norm:.6f}")

    # Optimizer step
    b_before = q0_B.clone()
    optimizer.step()
    b_after = q0_B.clone()
    delta_b = (b_after - b_before).float().norm().item()
    print(f"\n[11] Optimizer Step Verification:")
    print(f"    lora_B parameter delta after step: {delta_b:.6f}")

    # Compute loss after 1 step
    with torch.no_grad():
        out_step1 = lora_model(
            input_ids=full_ids.unsqueeze(0),
            attention_mask=enc_full["attention_mask"],
            labels=masked_labels.unsqueeze(0),
        )
        step1_loss = out_step1.loss.item()
    print(f"    Loss before step: {step0_loss:.4f}")
    print(f"    Loss after step : {step1_loss:.4f} (Delta: {step1_loss - step0_loss:+.4f})")
    print("=" * 70)


if __name__ == "__main__":
    run_diagnostics()

