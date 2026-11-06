"""AEROLITH Fine-Tuned Model Evaluator.

Compares:
  1. Deterministic baseline (existing interpreter)
  2. Pretrained qwen2.5:0.5b via Ollama (before fine-tuning)
  3. Fine-tuned LoRA adapter (after training)

on the engineering-v2.2.0 held-out test split and the Gold-15 set.

Usage:
  python ml-training/scripts/evaluate_finetuned.py [--adapter-dir .local-models/runs/qwen3-0.6b-aerolith-lora]
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# ─── Paths ────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_JSONL = REPO_ROOT / "data/learning/engineering-v2.2.0/test.jsonl"
ARTIFACTS_DIR = REPO_ROOT / "artifacts"
DEFAULT_ADAPTER = REPO_ROOT / ".local-models/runs/qwen2.5-0.5b-aerolith-v2"
LOCAL_MODEL_PATH = os.environ.get("LOCAL_MODEL_PATH", r"C:\Users\prasu\.cache\hf_direct\Qwen2.5-0.5B-Instruct")

sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "services/api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_loader import load_model_no_mmap


# ─── Scoring ──────────────────────────────────────────────────────────────────

NUMERIC_FIELDS = {
    "num_teeth_pinion", "num_teeth_gear", "module_mm", "face_width_mm",
    "pressure_angle_deg", "helix_angle_deg", "gear_ratio",
    "pinion_teeth", "gear_teeth", "module", "face_width",
}
CATEGORY_FIELDS = {
    "gear_type", "material_pinion", "material_gear",
    "status", "category", "clarification_needed",
}


def score_prediction(pred: dict, gold: dict) -> dict:
    """Return field-level and aggregate scores."""
    fields = set(gold.keys()) | set(pred.keys())
    results = {}
    exact_matches = 0
    total_fields = 0
    missing_fields = 0
    invented_fields = 0

    for field in fields:
        g = gold.get(field)
        p = pred.get(field)
        if g is not None and p is None:
            missing_fields += 1
        if g is None and p is not None:
            invented_fields += 1

        if g is None and p is None:
            continue
        total_fields += 1

        if field in NUMERIC_FIELDS:
            try:
                gv = float(g) if g is not None else None
                pv = float(p) if p is not None else None
                match = gv is not None and pv is not None and abs(gv - pv) < 1e-4
            except (TypeError, ValueError):
                match = g == p
        else:
            match = g == p

        results[field] = {"gold": g, "pred": p, "match": match}
        if match:
            exact_matches += 1

    schema_valid = isinstance(pred, dict) and len(pred) > 0
    # Contradiction handling check: if gold expects error/invalid/contradiction
    gold_has_contradiction = any(k in gold for k in ["invalid", "error", "contradiction", "conflicts"]) or gold.get("status") in ["INVALID", "CONTRADICTION"]
    pred_has_contradiction = any(k in pred for k in ["invalid", "error", "contradiction", "conflicts"]) or pred.get("status") in ["INVALID", "CONTRADICTION"]
    contradiction_correct = (gold_has_contradiction == pred_has_contradiction) if gold_has_contradiction else None

    return {
        "field_results": results,
        "exact_match": exact_matches == total_fields and total_fields > 0,
        "field_accuracy": exact_matches / max(total_fields, 1),
        "schema_valid": schema_valid,
        "missing_fields": missing_fields,
        "invented_fields": invented_fields,
        "contradiction_correct": contradiction_correct,
    }


def parse_json_output(text: str) -> dict:
    """Extract JSON object from model output text."""
    text = text.strip()
    # Find first { ... }
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}


# ─── Evaluators ───────────────────────────────────────────────────────────────

def eval_base_direct(test_examples: list[dict]) -> list[dict]:
    """Run pure base model (without LoRA) directly on test examples."""
    import torch

    model_source = LOCAL_MODEL_PATH or r"C:\Users\prasu\.cache\hf_direct\Qwen2.5-0.5B-Instruct"
    print(f"  Loading pure base model from: {model_source}", flush=True)
    model, tokenizer = load_model_no_mmap(model_source, target_dtype=torch.bfloat16, verbose=False)
    model.eval()
    device = "cpu"

    SYSTEM_MSG = (
        "You are AEROLITH's engineering parameter extraction and constraint model. "
        "Output one valid JSON object adhering strictly to the required schema. "
        "Never invent unmentioned dimensions or make unsubstantiated safety claims."
    )

    results = []
    for idx, ex in enumerate(test_examples, 1):
        print(f"    [Base] Evaluating sample {idx}/{len(test_examples)} ({ex.get('id', 'unknown')})...", flush=True)
        user_payload = {
            "task_category": ex.get("task_category", "requirement_extraction"),
            "input": ex["input"],
            "context": ex.get("context", {}),
        }
        messages = [
            {"role": "system", "content": SYSTEM_MSG},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        enc = tokenizer(prompt, return_tensors="pt").to(device)

        gc.collect()
        t0 = time.perf_counter()
        with torch.inference_mode():
            out = model.generate(
                **enc,
                max_new_tokens=120,
                do_sample=False,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        latency = time.perf_counter() - t0

        gen_ids = out[0][enc["input_ids"].shape[1]:]
        gen_text = tokenizer.decode(gen_ids, skip_special_tokens=True)
        pred = parse_json_output(gen_text)
        gold = ex.get("expected_output", {})
        scored = score_prediction(pred, gold)
        scored["sample_id"] = ex.get("id")
        scored["raw_output"] = gen_text[:300]
        scored["latency_ms"] = round(latency * 1000, 1)
        results.append(scored)

    del model, tokenizer
    gc.collect()
    return results


def eval_finetuned(adapter_dir: Path, test_examples: list[dict]) -> list[dict]:
    """Run fine-tuned LoRA adapter on test examples."""
    import torch
    from peft import PeftModel

    model_source = LOCAL_MODEL_PATH or r"C:\Users\prasu\.cache\hf_direct\Qwen2.5-0.5B-Instruct"

    print(f"  Loading base model + LoRA adapter from: {adapter_dir}", flush=True)
    base, tokenizer = load_model_no_mmap(model_source, target_dtype=torch.bfloat16, verbose=False)
    model = PeftModel.from_pretrained(base, str(adapter_dir))
    model.to(torch.bfloat16)
    model.eval()
    device = "cpu"

    SYSTEM_MSG = (
        "You are AEROLITH's engineering parameter extraction and constraint model. "
        "Output one valid JSON object adhering strictly to the required schema. "
        "Never invent unmentioned dimensions or make unsubstantiated safety claims."
    )

    results = []
    for idx, ex in enumerate(test_examples, 1):
        print(f"    [LoRA] Evaluating sample {idx}/{len(test_examples)} ({ex.get('id', 'unknown')})...", flush=True)
        user_payload = {
            "task_category": ex.get("task_category", "requirement_extraction"),
            "input": ex["input"],
            "context": ex.get("context", {}),
        }
        messages = [
            {"role": "system", "content": SYSTEM_MSG},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        enc = tokenizer(prompt, return_tensors="pt").to(device)

        gc.collect()
        t0 = time.perf_counter()
        with torch.inference_mode():
            out = model.generate(
                **enc,
                max_new_tokens=120,
                do_sample=False,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        latency = time.perf_counter() - t0

        gen_ids = out[0][enc["input_ids"].shape[1]:]
        gen_text = tokenizer.decode(gen_ids, skip_special_tokens=True)
        pred = parse_json_output(gen_text)
        gold = ex.get("expected_output", {})
        scored = score_prediction(pred, gold)
        scored["sample_id"] = ex.get("id")
        scored["raw_output"] = gen_text[:300]
        scored["latency_ms"] = round(latency * 1000, 1)
        results.append(scored)

    del model, base, tokenizer
    gc.collect()
    return results


def eval_ollama(model_name: str, test_examples: list[dict]) -> list[dict]:
    """Run Ollama model on test examples."""
    import urllib.request

    SYSTEM_MSG = (
        "You are AEROLITH's engineering parameter extraction model. "
        "Output ONLY a valid JSON object with the extracted parameters. "
        "Never invent values not mentioned in the input."
    )

    results = []
    for ex in test_examples:
        user_content = ex["input"]
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": SYSTEM_MSG},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 200},
        }
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        t0 = time.perf_counter()
        try:
            resp = urllib.request.urlopen(req, timeout=60)
            raw = json.loads(resp.read())
            gen_text = raw["message"]["content"]
        except Exception as e:
            gen_text = ""
            print(f"    Ollama error: {e}", flush=True)
        latency = time.perf_counter() - t0

        pred = parse_json_output(gen_text)
        gold = ex.get("expected_output", {})
        scored = score_prediction(pred, gold)
        scored["raw_output"] = gen_text[:300]
        scored["latency_ms"] = round(latency * 1000, 1)
        results.append(scored)

    return results


def eval_deterministic(test_examples: list[dict]) -> list[dict]:
    """Run deterministic baseline on test examples."""
    try:
        from aeropkmech.intelligence import extract_local
    except ImportError:
        print("  Warning: could not import aeropkmech.intelligence.extract_local")
        return []

    results = []
    for idx, ex in enumerate(test_examples, 1):
        t0 = time.perf_counter()
        ext = extract_local(ex["input"])
        latency = time.perf_counter() - t0

        pred = {k: v for k, v in ext.proposal.model_dump().items() if v is not None}
        gold = ex.get("expected_output", {})
        scored = score_prediction(pred, gold)
        scored["sample_id"] = ex.get("id")
        scored["raw_output"] = json.dumps(ext.proposal.model_dump(), default=str)
        scored["latency_ms"] = round(latency * 1000, 1)
        results.append(scored)

    return results


# ─── Reporting ────────────────────────────────────────────────────────────────

def summarize(name: str, results: list[dict]) -> dict:
    n = len(results)
    if n == 0:
        return {"model": name, "n": 0}
    exact = sum(1 for r in results if r.get("exact_match")) / n
    field_acc = sum(r.get("field_accuracy", 0) for r in results) / n
    schema_valid = sum(1 for r in results if r.get("schema_valid")) / n
    avg_latency = sum(r.get("latency_ms", 0) for r in results) / n
    avg_missing = sum(r.get("missing_fields", 0) for r in results) / n
    avg_invented = sum(r.get("invented_fields", 0) for r in results) / n
    return {
        "model": name,
        "n": n,
        "exact_match_rate": round(exact, 3),
        "mean_field_accuracy": round(field_acc, 3),
        "schema_valid_rate": round(schema_valid, 3),
        "mean_missing_fields": round(avg_missing, 2),
        "mean_invented_fields": round(avg_invented, 2),
        "mean_latency_ms": round(avg_latency, 1),
    }


def print_table(summaries: list[dict]):
    print(f"\n{'Model':<40} {'N':>4} {'ExactMatch':>10} {'FieldAcc':>8} {'Schema':>6} {'Missing':>7} {'Invent':>7} {'Latency':>8}")
    print("-" * 96)
    for s in summaries:
        print(
            f"{s['model']:<40} {s['n']:>4} "
            f"{s.get('exact_match_rate', 0):>10.1%} "
            f"{s.get('mean_field_accuracy', 0):>8.1%} "
            f"{s.get('schema_valid_rate', 0):>6.1%} "
            f"{s.get('mean_missing_fields', 0):>7.1f} "
            f"{s.get('mean_invented_fields', 0):>7.1f} "
            f"{s.get('mean_latency_ms', 0):>7.0f}ms"
        )


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="AEROLITH Fine-Tuned Model Evaluator")
    parser.add_argument("--adapter-dir", default=str(DEFAULT_ADAPTER), help="Path to LoRA adapter directory")
    parser.add_argument("--skip-base", action="store_true", help="Skip pure base model evaluation")
    parser.add_argument("--skip-deterministic", action="store_true", help="Skip deterministic baseline")
    parser.add_argument("--use-ollama", action="store_true", help="Use Ollama instead of direct PyTorch for base model")
    parser.add_argument("--max-samples", type=int, default=None, help="Maximum number of test samples to evaluate")
    args = parser.parse_args()

    adapter_dir = Path(args.adapter_dir)
    if not adapter_dir.exists():
        print(f"ERROR: Adapter directory not found: {adapter_dir}", file=sys.stderr)
        sys.exit(1)

    # Load test examples
    if not TEST_JSONL.exists():
        print(f"ERROR: Test set not found: {TEST_JSONL}", file=sys.stderr)
        sys.exit(1)
    test_examples = [json.loads(l) for l in TEST_JSONL.read_text().splitlines() if l.strip()]
    if args.max_samples:
        test_examples = test_examples[:args.max_samples]
    print(f"Loaded {len(test_examples)} test examples from {TEST_JSONL}")

    all_summaries = []
    all_results = {}

    # 1. Deterministic baseline
    if not args.skip_deterministic:
        print("\n[1/3] Evaluating deterministic AEROLITH baseline (extract_local)...")
        det_results = eval_deterministic(test_examples)
        if det_results:
            det_summary = summarize("Deterministic Baseline (extract_local)", det_results)
            all_summaries.append(det_summary)
            all_results["deterministic_baseline"] = det_results
            print(f"      Exact match: {det_summary['exact_match_rate']:.1%}, Field acc: {det_summary['mean_field_accuracy']:.1%}")

    # 2. Base model evaluation
    if not args.skip_base:
        if args.use_ollama:
            print("\n[2/3] Evaluating pretrained qwen2.5:0.5b via Ollama...")
            base_results = eval_ollama("qwen2.5:0.5b", test_examples)
            base_summary = summarize("Qwen2.5-0.5B (Pretrained, Ollama)", base_results)
        else:
            print("\n[2/3] Evaluating pure base Qwen2.5-0.5B-Instruct (Direct PyTorch)...")
            base_results = eval_base_direct(test_examples)
            base_summary = summarize("Qwen2.5-0.5B-Instruct (Pure Base)", base_results)

        all_summaries.append(base_summary)
        all_results["base_model"] = base_results
        print(f"      Exact match: {base_summary['exact_match_rate']:.1%}, Field acc: {base_summary['mean_field_accuracy']:.1%}")

    # 3. Fine-tuned LoRA
    print(f"\n[3/3] Evaluating fine-tuned LoRA adapter from {adapter_dir}...")
    ft_results = eval_finetuned(adapter_dir, test_examples)
    ft_summary = summarize("Qwen2.5-0.5B + AEROLITH LoRA (Fine-Tuned)", ft_results)
    all_summaries.append(ft_summary)
    all_results["finetuned_lora"] = ft_results
    print(f"      Exact match: {ft_summary['exact_match_rate']:.1%}, Field acc: {ft_summary['mean_field_accuracy']:.1%}")

    # Print table
    print_table(all_summaries)

    # Save report
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    report = {
        "evaluation_type": "3way_comparison_base_lora_deterministic",
        "adapter_dir": str(adapter_dir),
        "test_set": str(TEST_JSONL),
        "n_examples": len(test_examples),
        "summaries": all_summaries,
        "per_example": all_results,
    }
    out_path = ARTIFACTS_DIR / "finetuned_eval_report.json"
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nFull report saved to: {out_path}")


if __name__ == "__main__":
    main()

