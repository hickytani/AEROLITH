from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .domain import Design

REPORT_VERSION = "engineering-note-0.2"
INDEX_NAME = "artifact-index.json"


def _read_index(index: Path) -> dict:
    try:
        data = json.loads(index.read_text(encoding="utf-8")) if index.exists() else {"schema_version": 1, "artifacts": []}
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Artifact index is unreadable at {index}.") from exc
    required = {"artifact_id", "kind", "filename", "revision", "design_sha256", "sha256", "generator_version", "created_at"}
    safe_item = lambda item: (
        isinstance(item.get("artifact_id"), str)
        and item.get("kind") in {"assembly", "pinion", "gear", "report"}
        and isinstance(item.get("filename"), str)
        and Path(item["filename"]).name == item["filename"]
        and re.fullmatch(r"[A-Za-z0-9_.-]+", item["filename"]) is not None
        and isinstance(item.get("revision"), int)
        and not isinstance(item.get("revision"), bool)
        and item["revision"] > 0
        and re.fullmatch(r"[0-9a-f]{64}", str(item.get("design_sha256", ""))) is not None
        and re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))) is not None
        and isinstance(item.get("generator_version"), str)
        and isinstance(item.get("created_at"), str)
    )
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != 1
        or not isinstance(data.get("artifacts"), list)
        or any(not isinstance(item, dict) or not required.issubset(item) or not safe_item(item) for item in data["artifacts"])
    ):
        raise RuntimeError(f"Artifact index has an unsupported format at {index}.")
    return data


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def publish(data: bytes, directory: Path, design: Design, kind: str, extension: str, generator_version: str) -> tuple[Path, dict]:
    digest = hashlib.sha256(data).hexdigest()
    filename = f"{kind}-r{design.revision}-{generator_version}-{digest[:12]}.{extension}"
    path = directory / filename
    _atomic_write(path, data)
    metadata = {
        "artifact_id": f"{kind}:r{design.revision}:{digest[:16]}",
        "kind": kind,
        "filename": filename,
        "revision": design.revision,
        "design_sha256": hashlib.sha256(design.model_dump_json().encode("utf-8")).hexdigest(),
        "sha256": digest,
        "generator_version": generator_version,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    index = directory / INDEX_NAME
    existing = _read_index(index)
    artifacts = [item for item in existing["artifacts"] if item.get("artifact_id") != metadata["artifact_id"]]
    artifacts.append(metadata)
    _atomic_write(index, json.dumps({"schema_version": 1, "artifacts": artifacts}, indent=2).encode("utf-8"))
    return path, metadata


def list_artifacts(directory: Path, current: Design) -> list[dict]:
    index = directory / INDEX_NAME
    if not index.exists():
        return []
    data = _read_index(index)
    current_digest = hashlib.sha256(current.model_dump_json().encode("utf-8")).hexdigest()
    result = []
    for item in data["artifacts"]:
        filename = item.get("filename", "")
        safe_file = isinstance(filename, str) and Path(filename).name == filename
        result.append({
            **item,
            "stale": item.get("revision") != current.revision or item.get("design_sha256") != current_digest,
            "available": safe_file and (directory / filename).is_file(),
        })
    return result
