"""Validate split membership and provenance without loading ML frameworks."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def validate(directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    schema_version = manifest.get("schema_version")
    if not manifest.get("dataset_version") or schema_version not in {"1.0", "2.0"}:
        raise ValueError("Invalid dataset manifest.")
    ids: set[str] = set()
    split_ids = {}
    hashes = {}
    for split in ("train", "validation", "test"):
        path = directory / f"{split}.jsonl"
        raw = path.read_bytes()
        hashes[split] = hashlib.sha256(raw).hexdigest()
        current = []
        for line in raw.decode("utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not row.get("id") or row["id"] in ids or row.get("split") != split:
                raise ValueError(f"Invalid or overlapping record in {split}.")
            provenance = row.get("provenance", {})
            if provenance.get("origin") not in {"synthetic_hand_authored", "reviewed_execution_trace"} or not provenance.get("license"):
                raise ValueError("Every example requires explicit provenance and a license.")
            if schema_version == "1.0":
                if provenance.get("license") != manifest.get("example_license"):
                    raise ValueError("Example license differs from dataset manifest.")
                input_text, target = row.get("text"), row.get("expected")
            else:
                if row.get("dataset_version") != manifest["dataset_version"] or row.get("schema_version") != "1.0":
                    raise ValueError("Engineering v2 example has a mismatched schema or dataset version.")
                if row.get("task_category") not in manifest.get("supported_categories", []):
                    raise ValueError("Unsupported task category.")
                if row.get("review_status") not in {"SYNTHETIC_REVIEWED", "HUMAN_APPROVED"}:
                    raise ValueError("Unreviewed data cannot be used for training.")
                input_text, target = row.get("input"), row.get("expected_output")
            if not isinstance(input_text, str) or not input_text.strip() or not isinstance(target, dict):
                raise ValueError("Record must include non-empty input and structured target.")
            ids.add(row["id"])
            current.append(row["id"])
        if not current:
            raise ValueError(f"The {split} split is empty.")
        split_ids[split] = current
    return {"dataset_version": manifest["dataset_version"], "counts": {k: len(v) for k, v in split_ids.items()}, "sha256": hashes, "examples": len(ids)}


if __name__ == "__main__":
    try:
        print(json.dumps(validate(Path(sys.argv[1])), indent=2))
    except (OSError, ValueError, json.JSONDecodeError, IndexError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}))
        raise SystemExit(2)
