from pathlib import Path

import pytest

from aeropkmech.evaluation import evaluate_dataset


DATASET = Path(__file__).resolve().parents[3] / "data" / "learning"


def test_synthetic_requirement_baseline_evaluation_has_separate_splits():
    report = evaluate_dataset(DATASET)
    assert report["dataset_version"] == "gear-requirements-synthetic-1.0"
    assert report["baseline"] == "deterministic-patterns-v1"
    assert report["splits"]["train"]["examples"] == 3
    assert report["splits"]["validation"]["examples"] == 1
    assert report["splits"]["test"]["examples"] == 2
    assert report["splits"]["test"]["exact_example_accuracy"] == 1
    assert "independent engineering validation evidence" in report["note"]


def test_evaluator_rejects_ambiguous_provenance(tmp_path):
    (tmp_path / "manifest.json").write_text((DATASET / "manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    for split in ("train", "validation", "test"):
        source = DATASET / f"{split}.jsonl"
        line = source.read_text(encoding="utf-8").splitlines()[0]
        (tmp_path / f"{split}.jsonl").write_text(line + "\n", encoding="utf-8")
    path = tmp_path / "test.jsonl"
    import json
    item = json.loads(path.read_text(encoding="utf-8"))
    item["provenance"]["origin"] = "unknown"
    path.write_text(json.dumps(item), encoding="utf-8")
    with pytest.raises(ValueError, match="synthetic provenance"):
        evaluate_dataset(tmp_path)
