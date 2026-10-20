"""Paired Ollama evaluation on held-out engineering-v2 test records."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx


def subset_exact(expected, actual) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(key in actual and subset_exact(value, actual[key]) for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(subset_exact(a, b) for a, b in zip(expected, actual))
    return expected == actual


async def infer(client: httpx.AsyncClient, model: str, row: dict) -> tuple[dict | None, str | None]:
    expected_shape = row["expected_output"]
    schema = {key: "value" for key in expected_shape}
    prompt = json.dumps({"task_category": row["task_category"], "input": row["input"], "context": row.get("context", {}), "required_output_keys": schema}, ensure_ascii=False)
    response = await client.post("http://127.0.0.1:11434/api/generate", json={"model": model,
        "system": "Return one JSON object for this engineering task. Use only supplied evidence. Do not claim safety, performance, or calculations without evidence.",
        "prompt": prompt, "format": "json", "stream": False, "options": {"num_predict": 700}})
    response.raise_for_status()
    raw = response.json().get("response", "")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None, "invalid_json"
    return (parsed, None) if isinstance(parsed, dict) else (None, "output_not_object")


async def evaluate(args) -> dict:
    dataset = Path(args.dataset)
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    thresholds = json.loads((Path(__file__).resolve().parents[1] / "configs" / "evaluation-thresholds.json").read_text(encoding="utf-8"))
    if not re.fullmatch(r"[0-9a-f]{40}", args.base_revision) or not re.fullmatch(r"[0-9a-f]{40}", args.candidate_revision):
        raise ValueError("Evaluation requires immutable 40-character base and candidate revisions.")
    rows = [json.loads(line) for line in (dataset / "test.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise ValueError("Held-out test split is empty.")
    raw = (dataset / "test.jsonl").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    output = {"suite_version": thresholds["suite_version"], "dataset_version": manifest["dataset_version"], "test_sha256": digest,
        "base": {"model": args.base_model, "revision": args.base_revision},
        "candidate": {"model": args.candidate_model, "revision": args.candidate_revision},
        "started_at": datetime.now(timezone.utc).isoformat(), "examples": len(rows), "metrics": {}, "failures": []}
    async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
        for label, model in (("base", args.base_model), ("candidate", args.candidate_model)):
            valid = exact = 0
            for row in rows:
                try:
                    actual, error = await infer(client, model, row)
                except (httpx.HTTPError, ValueError) as exc:
                    actual, error = None, type(exc).__name__
                valid += int(actual is not None)
                matched = actual is not None and subset_exact(row["expected_output"], actual)
                exact += int(matched)
                if not matched:
                    output["failures"].append({"model": label, "example_id": row["id"], "task_category": row["task_category"], "error": error,
                                                "actual": actual})
            output["metrics"][label] = {"json_valid_rate": valid / len(rows), "exact_expected_subset_accuracy": exact / len(rows)}
    output["finished_at"] = datetime.now(timezone.utc).isoformat()
    output["promotion_eligible"] = (output["metrics"]["candidate"]["json_valid_rate"] >= thresholds["minimum_candidate_json_valid_rate"]
                                    and output["metrics"]["candidate"]["exact_expected_subset_accuracy"] >= output["metrics"]["base"]["exact_expected_subset_accuracy"])
    output["automatic_promotion"] = thresholds["automatic_promotion"]
    output["note"] = "Tiny synthetic held-out set; paired exact-field scoring only. Promotion remains a human decision and is not safety evidence."
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/learning/engineering-v2")
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--base-revision", required=True)
    parser.add_argument("--candidate-model", required=True)
    parser.add_argument("--candidate-revision", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = asyncio.run(evaluate(args))
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
