"""Deterministic held-out evaluation for the requirement-extraction baseline."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .intelligence import extract_local


def evaluate_dataset(directory: Path) -> dict[str, Any]:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "1.0" or manifest.get("task") != "natural_language_to_reviewable_gear_specification":
        raise ValueError("Unsupported requirement dataset manifest.")
    splits: dict[str, list[dict[str, Any]]] = {}
    seen: set[str] = set()
    for split in ("train", "validation", "test"):
        entries = []
        for line in (directory / f"{split}.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if item.get("split") != split or not item.get("id") or item["id"] in seen:
                raise ValueError(f"Invalid or duplicate dataset example in {split}.")
            if item.get("provenance", {}).get("origin") != "synthetic_hand_authored":
                raise ValueError("Every current example must declare its synthetic provenance.")
            if item.get("provenance", {}).get("license") != manifest.get("example_license"):
                raise ValueError("Example license metadata must match the dataset manifest.")
            seen.add(item["id"])
            entries.append(item)
        if not entries:
            raise ValueError(f"Dataset split '{split}' must contain at least one example.")
        splits[split] = entries

    report = {"dataset_version": manifest["dataset_version"], "baseline": "deterministic-patterns-v1", "splits": {}}
    for split, entries in splits.items():
        exact = 0
        slots = 0
        slots_correct = 0
        parsed_correct = 0
        for item in entries:
            output = extract_local(item["text"])
            expected = item["expected"]
            actual_values = output.proposal.model_dump()
            item_exact = True
            for field, expected_value in expected.get("proposal", {}).items():
                slots += 1
                actual_value = actual_values.get(field)
                matches = (
                    math.isclose(float(actual_value), float(expected_value), rel_tol=0, abs_tol=1e-9)
                    if isinstance(expected_value, (int, float)) and actual_value is not None
                    else actual_value == expected_value
                )
                slots_correct += int(matches)
                item_exact &= matches
            if output.parsed != expected["parsed"] or len(output.conflicts) != expected.get("conflict_count", 0):
                item_exact = False
            parsed_correct += int(output.parsed == expected["parsed"])
            exact += int(item_exact)
        report["splits"][split] = {
            "examples": len(entries), "exact_example_accuracy": exact / len(entries),
            "slot_accuracy": slots_correct / slots if slots else 1.0,
            "parsed_flag_accuracy": parsed_correct / len(entries),
        }
    report["note"] = "Synthetic hand-authored evaluation only; no training, external data, or independent engineering validation evidence."
    return report


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[3] / "data" / "learning"
    print(json.dumps(evaluate_dataset(root), indent=2))
