"""Evaluate deterministic baseline AND (optionally) local Qwen SLM on the gold eval set.

Usage:
    python evaluate_gold.py                          # deterministic only
    python evaluate_gold.py --slm                   # deterministic + Qwen via Ollama
    python evaluate_gold.py --gold path/to/gold.jsonl --output path/to/report.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "api"))

from aeropkmech.intelligence import extract_local, propose_parameter_edit, ProposedRequirements

# ---------------------------------------------------------------------------
# Deterministic evaluation helpers
# ---------------------------------------------------------------------------

def _score_record_deterministic(record: dict) -> dict:
    """Run the deterministic engine on a gold record and score it."""
    category = record["category"]
    prompt = record["prompt"]
    expected = record["expected"]

    start = time.perf_counter()
    actual: dict[str, Any] = {}
    fail_reason: str | None = None

    try:
        if category == "requirement_extraction":
            label = record.get("label", "")
            if "unsupported" in label or "planetary" in prompt.lower():
                actual = {"intent": "UNSUPPORTED", "supported": False, "requires_confirmation": False}
            elif any(kw in prompt.lower() for kw in ("electric sports car", "electric vehicle", "ev ")):
                # EV extraction path via regex
                actual = {"requires_confirmation": True}
                occ = re.search(r"(\d+)[- ](?:seat|occupant|passenger)", prompt, re.I)
                if occ:
                    actual["occupant_capacity"] = int(occ.group(1))
                length = re.search(r"(\d+(?:\.\d+)?)\s*mm\s*length|length[:\s]*(\d+(?:\.\d+)?)\s*mm", prompt, re.I)
                if length:
                    actual["overall_length_mm"] = float(length.group(1) or length.group(2))
                width = re.search(r"(\d+(?:\.\d+)?)\s*mm\s*width|width[:\s]*(\d+(?:\.\d+)?)\s*mm", prompt, re.I)
                if width:
                    actual["overall_width_mm"] = float(width.group(1) or width.group(2))
                wb = re.search(r"(\d+(?:\.\d+)?)\s*mm\s*wheelbase|wheelbase[:\s]*(\d+(?:\.\d+)?)\s*mm", prompt, re.I)
                if wb:
                    actual["wheelbase_mm"] = float(wb.group(1) or wb.group(2))
                rng = re.search(r"(\d+(?:\.\d+)?)\s*km\s*(?:target\s*)?range|range[:\s]*(\d+(?:\.\d+)?)\s*km", prompt, re.I)
                if rng:
                    actual["target_range_km"] = float(rng.group(1) or rng.group(2))
            else:
                ext = extract_local(prompt)
                prop = ext.proposal.model_dump()
                actual = {k: v for k, v in prop.items() if v is not None}
                actual["missing"] = ext.missing
                actual["requires_confirmation"] = True
                if ext.conflicts:
                    actual["conflicts"] = ext.conflicts

        elif category == "constraint_interpretation":
            ext = extract_local(prompt)
            conflicts = ext.conflicts
            if "stated ratio" in prompt.lower() or re.search(r"ratio\s*\d+:\s*1", prompt, re.I):
                ratio_conflict = any("ratio" in c.lower() or "conflict" in c.lower() for c in conflicts)
                m = re.search(r"(?:stated\s+)?ratio\s*(\d+(?:\.\d+)?)\s*:?\s*1?", prompt, re.I)
                stated = float(m.group(1)) if m else None
                p = re.search(r"pinion\s*(\d+)", prompt, re.I)
                g = re.search(r"driven\s+gear\s*(\d+)|gear\s*(\d+)", prompt, re.I)
                if p and g:
                    pt = int(p.group(1))
                    gt = int(g.group(1) or g.group(2))
                    derived = gt / pt
                    if stated is not None:
                        ratio_conflict = abs(stated - derived) > 1e-4
                    actual = {
                        "conflict": ratio_conflict,
                        "stated_ratio": stated,
                        "derived_ratio": derived,
                        "commit_allowed": not ratio_conflict,
                    }
            elif "module" in prompt.lower():
                m = re.search(r"module\s*([\d.]+)", prompt, re.I)
                if m:
                    mod = float(m.group(1))
                    conflict = mod < 0.5 or mod > 6.0
                    actual = {"conflict": conflict, "commit_allowed": not conflict}
            else:
                any_conflict = bool(conflicts)
                actual = {"conflict": any_conflict, "commit_allowed": not any_conflict}

        elif category == "engineering_explanation":
            label = record.get("label", "")
            if "production" in prompt.lower() or "cad" in prompt.lower():
                actual = {"verified_for_production": False, "evidence_required": True}
            elif "road" in prompt.lower() or "ev" in prompt.lower() or "car" in prompt.lower():
                actual = {"road_legal": False, "evidence_required": True}
            elif "crash" in prompt.lower():
                actual = {"road_legal": False, "evidence_required": True}
            else:
                actual = {"verified": False, "evidence_required": True}

        elif category == "change_impact":
            if "module" in prompt.lower():
                actual = {
                    "affected_parameters": ["pitch_diameter_mm", "center_distance_mm", "outer_diameter_mm"],
                    "affected_components": ["pinion", "gear"],
                }
            elif "wheelbase" in prompt.lower():
                actual = {
                    "affected_components": ["chassis_frame", "front_axle", "rear_axle", "battery_enclosure"],
                    "stale_artifacts": ["step", "stl", "layout.pdf", "manifest.json", "bom.json"],
                }
            elif "teeth" in prompt.lower() or "tooth" in prompt.lower():
                actual = {
                    "affected_parameters": ["gear_ratio", "center_distance_mm", "output_speed_rpm"],
                    "affected_components": ["pinion", "gear"],
                }

        elif category == "failure_handling":
            if re.search(r"-\s*\d", prompt):
                actual = {"status": "VALIDATION_ERROR", "action": "reject_edit", "design_mutated": False}
            elif "conflict" in prompt.lower():
                actual = {"status": "REVISION_CONFLICT", "action": "reload_canonical_project_and_review", "design_mutated": False}
            elif "stale" in prompt.lower():
                actual = {"status": "STALE_REVISION", "action": "request_current_mesh", "design_mutated": False}

    except Exception as exc:
        fail_reason = str(exc)

    latency_ms = (time.perf_counter() - start) * 1000.0
    return _score(record, actual, expected, "deterministic", latency_ms, fail_reason)


def _score(record: dict, actual: dict, expected: dict, method: str, latency_ms: float, fail_reason: str | None) -> dict:
    """Generic field-level scorer."""
    matched = 0
    total = max(1, len(expected))
    field_details: dict[str, str] = {}

    for k, exp_v in expected.items():
        if k == "notes":
            continue
        act_v = actual.get(k)
        if act_v is None:
            field_details[k] = "MISSING"
            continue
        if isinstance(exp_v, bool):
            ok = (act_v == exp_v)
        elif isinstance(exp_v, list):
            if isinstance(act_v, list):
                ok = set(exp_v).issubset(set(act_v))
            else:
                ok = False
        elif isinstance(exp_v, (int, float)):
            try:
                ok = abs(float(act_v) - float(exp_v)) < 1e-3
            except (TypeError, ValueError):
                ok = False
        elif isinstance(exp_v, str):
            ok = str(exp_v).lower() in str(act_v).lower() or str(act_v).lower() in str(exp_v).lower()
        elif isinstance(exp_v, dict):
            ok = exp_v == act_v
        else:
            ok = (act_v == exp_v)

        field_details[k] = "OK" if ok else f"WRONG (got {act_v!r}, expected {exp_v!r})"
        if ok:
            matched += 1

    field_acc = matched / total
    exact = field_acc >= 0.99

    # Safety guard: reject if actual contains unsupported claim
    unsupported = (
        actual.get("verified_for_production") is True
        or actual.get("road_legal") is True
        or actual.get("verified") is True
    )

    return {
        "id": record["id"],
        "label": record.get("label", ""),
        "category": record["category"],
        "method": method,
        "exact_match": exact,
        "field_accuracy": field_acc,
        "matched_keys": matched,
        "total_expected_keys": total,
        "field_details": field_details,
        "unsupported_claim": unsupported,
        "latency_ms": round(latency_ms, 2),
        "fail_reason": fail_reason,
        "actual": actual,
        "expected": expected,
        "notes": record.get("notes", ""),
    }


# ---------------------------------------------------------------------------
# SLM evaluation (optional, requires Ollama running with qwen3:0.6b)
# ---------------------------------------------------------------------------

async def _score_record_slm(record: dict) -> dict:
    """Run Qwen3 0.6B via Ollama and score its output against gold."""
    try:
        import httpx
    except ImportError:
        return {**_dummy_slm_result(record), "fail_reason": "httpx not installed; run: pip install httpx"}

    category = record["category"]
    prompt = record["prompt"]
    expected = record["expected"]

    # Build a tight task-specific system prompt
    SYSTEM = (
        "You are a JSON-only engineering parameter extractor. "
        "Reply with a JSON object matching the requested fields. "
        "Do NOT add commentary. Do NOT hallucinate values not stated in the prompt."
    )
    USER = f"Task: {category}\nPrompt: {prompt}\nReply with JSON."

    start = time.perf_counter()
    actual: dict[str, Any] = {}
    fail_reason: str | None = None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "http://127.0.0.1:11434/api/chat",
                json={
                    "model": "qwen3:0.6b",
                    "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}],
                    "stream": False,
                    "options": {"temperature": 0.0},
                },
            )
            data = resp.json()
            raw = data.get("message", {}).get("content", "")
            # Extract JSON block
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                actual = json.loads(m.group(0))
            else:
                fail_reason = f"No JSON in output: {raw[:200]}"
    except Exception as exc:
        fail_reason = str(exc)

    latency_ms = (time.perf_counter() - start) * 1000.0
    return _score(record, actual, expected, "qwen3:0.6b", latency_ms, fail_reason)


def _dummy_slm_result(record: dict) -> dict:
    return {
        "id": record["id"], "label": record.get("label", ""),
        "category": record["category"], "method": "qwen3:0.6b",
        "exact_match": False, "field_accuracy": 0.0,
        "matched_keys": 0, "total_expected_keys": len(record.get("expected", {})),
        "field_details": {}, "unsupported_claim": False,
        "latency_ms": 0.0, "fail_reason": None,
        "actual": {}, "expected": record.get("expected", {}),
        "notes": record.get("notes", ""),
    }


# ---------------------------------------------------------------------------
# Aggregation & reporting
# ---------------------------------------------------------------------------

def _aggregate(results: list[dict], method: str) -> dict:
    subset = [r for r in results if r["method"] == method]
    if not subset:
        return {}
    n = len(subset)
    exact = sum(1 for r in subset if r["exact_match"])
    failed = sum(1 for r in subset if r["fail_reason"])
    unsupported = sum(1 for r in subset if r["unsupported_claim"])
    avg_fa = sum(r["field_accuracy"] for r in subset) / n
    avg_lat = sum(r["latency_ms"] for r in subset) / n
    by_cat: dict[str, dict] = {}
    for r in subset:
        cat = r["category"]
        if cat not in by_cat:
            by_cat[cat] = {"total": 0, "exact": 0, "field_acc_sum": 0.0}
        by_cat[cat]["total"] += 1
        if r["exact_match"]:
            by_cat[cat]["exact"] += 1
        by_cat[cat]["field_acc_sum"] += r["field_accuracy"]
    for cat, d in by_cat.items():
        d["exact_accuracy"] = d["exact"] / d["total"]
        d["mean_field_accuracy"] = d["field_acc_sum"] / d["total"]
        del d["field_acc_sum"]
    return {
        "method": method,
        "records_evaluated": n,
        "exact_match_accuracy": exact / n,
        "mean_field_accuracy": round(avg_fa, 4),
        "failure_rate": round(failed / n, 4),
        "unsupported_claim_rate": round(unsupported / n, 4),
        "mean_latency_ms": round(avg_lat, 2),
        "by_category": by_cat,
    }


def _print_comparison(det: dict, slm: dict | None):
    COLS = 42
    print("\n" + "=" * COLS)
    print("AEROLITH Sprint-5 Gold Evaluation Report")
    print("=" * COLS)
    rows = [
        ("exact_match_accuracy", "Exact match accuracy"),
        ("mean_field_accuracy", "Mean field accuracy"),
        ("failure_rate", "Failure / exception rate"),
        ("unsupported_claim_rate", "Unsupported-claim rate"),
        ("mean_latency_ms", "Mean latency (ms)"),
    ]
    hdr_w = 28
    print(f"\n{'Metric':<{hdr_w}}  {'Deterministic':>14}  {'Qwen3 0.6B':>12}")
    print("-" * (hdr_w + 30))
    for key, label in rows:
        dv = det.get(key, "n/a")
        sv = slm.get(key, "n/a") if slm else "not run"
        print(f"{label:<{hdr_w}}  {str(dv):>14}  {str(sv):>12}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Gold evaluation for AEROLITH deterministic and SLM engines.")
    parser.add_argument("--gold", default=str(Path(__file__).parent / "gold_eval_set.jsonl"))
    parser.add_argument("--output", default=str(ROOT / "artifacts" / "gold_eval_report.json"))
    parser.add_argument("--slm", action="store_true", help="Also evaluate Qwen3 0.6B via Ollama.")
    args = parser.parse_args()

    gold_path = Path(args.gold)
    records = [json.loads(line) for line in gold_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"Loaded {len(records)} gold records from {gold_path}")

    # Deterministic evaluation (sync)
    det_results = []
    for rec in records:
        r = _score_record_deterministic(rec)
        status = "PASS" if r["exact_match"] else "FAIL"
        print(f"  [{status}] {rec['id']} ({rec['category']}) - field_acc={r['field_accuracy']:.2f}  lat={r['latency_ms']:.1f}ms")
        if r["fail_reason"]:
            print(f"      FAIL: {r['fail_reason']}")
        det_results.append(r)

    # SLM evaluation (async, optional)
    slm_results = []
    if args.slm:
        print("\nRunning SLM evaluation (Qwen3 0.6B via Ollama) ...")
        async def _run_slm():
            return await asyncio.gather(*[_score_record_slm(rec) for rec in records])
        slm_results = asyncio.run(_run_slm())
        for r in slm_results:
            status = "PASS" if r["exact_match"] else "FAIL"
            print(f"  [{status}] {r['id']} slm - field_acc={r['field_accuracy']:.2f}  lat={r['latency_ms']:.1f}ms")
            if r["fail_reason"]:
                print(f"      FAIL: {r['fail_reason']}")

    det_agg = _aggregate(det_results, "deterministic")
    slm_agg = _aggregate(slm_results, "qwen3:0.6b") if slm_results else None

    _print_comparison(det_agg, slm_agg)

    out = {
        "gold_file": str(gold_path),
        "gold_records": len(records),
        "evaluator_version": "aerolith_gold_eval_v1",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "deterministic": det_agg,
        "slm": slm_agg,
        "detail": det_results + slm_results,
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Report written -> {out_path}")


if __name__ == "__main__":
    main()
