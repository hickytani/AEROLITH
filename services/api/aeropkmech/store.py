from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock
import time
from uuid import uuid4

from pydantic import ValidationError

from .domain import Component, Design, Requirements

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(os.environ.get("AEROPKMECH_DATA_DIR", ROOT / "data"))
STATE_FILE = DATA_DIR / "project.json"
PROJECT_WRITE_LOCK = RLock()


class ProjectStateError(RuntimeError):
    """The persisted project exists but cannot be read or validated."""


class ProjectPersistenceError(RuntimeError):
    """A valid project could not be committed to local storage."""


class ProjectRevisionConflict(RuntimeError):
    def __init__(self, expected_revision: int, current_revision: int):
        self.expected_revision=expected_revision
        self.current_revision=current_revision
        super().__init__(f"Project revision advanced from {expected_revision} to {current_revision} during candidate generation.")


def default_design() -> Design:
    return Design(
        revision=1,
        requirements=Requirements(
            gear_ratio=3,
            input_torque_Nm=8,
            input_speed_rpm=900,
            module_mm=2,
            face_width_mm=12,
            pressure_angle_deg=20,
        ),
        assumptions=[
            "Ordinary unshifted external spur gears; sampled involute flanks at 20° pressure angle.",
            "Addendum m, dedendum 1.25m, zero nominal backlash, and a straight radial root connector below the base circle; not a cutter-generated trochoid.",
            "Illustrative equal bore size derived from module and the smaller root diameter; user bore/shaft requirements are not modeled.",
            "Ideal lossless power transmission for output speed and torque; strength and thermal capacity are not assessed.",
        ],
        components=[
            Component(id="pinion", name="Pinion", teeth=18),
            Component(id="gear", name="Driven gear", teeth=54),
        ],
        status={"geometry": "CALCULATED", "kinematics": "CALCULATED", "strength": "UNKNOWN", "thermal": "UNTESTED"},
    )


def load() -> Design:
    with PROJECT_WRITE_LOCK:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ProjectStateError(f"Project data directory is unavailable at {DATA_DIR}.") from exc
        if not STATE_FILE.exists():
            design = default_design()
            save(design)
            return design
        try:
            raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if raw.get("family") == "electric_vehicle":
                from .automotive import VehicleDesign
                return VehicleDesign.model_validate(raw)
            return Design.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise ProjectStateError(f"Persisted project is unreadable or invalid at {STATE_FILE}.") from exc


def save(design: Design) -> None:
    with PROJECT_WRITE_LOCK:
        _save_locked(design)


def save_if_revision(design: Design, expected_revision: int) -> None:
    """Process-local compare-and-swap for a fully validated, regenerated candidate."""
    with PROJECT_WRITE_LOCK:
        current=load()
        if current.revision!=expected_revision:
            raise ProjectRevisionConflict(expected_revision,current.revision)
        if design.revision != expected_revision + 1:
            raise ProjectPersistenceError(
                f"Conditional project commits must advance exactly one revision from {expected_revision}."
            )
        if design.id != current.id:
            raise ProjectPersistenceError("Conditional commits must preserve the active project identity.")
        _save_locked(design)


def _save_locked(design: Design) -> None:
    try:
        if design.family == "electric_vehicle":
            from .automotive import VehicleDesign
            validated = VehicleDesign.model_validate(design.model_dump(mode="json"))
        else:
            validated = Design.model_validate(design.model_dump(mode="json"))
    except ValidationError as exc:
        raise ProjectPersistenceError("Candidate project failed full schema validation; it was not saved.") from exc
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ProjectPersistenceError(f"Project data directory is unavailable at {DATA_DIR}.") from exc
    tmp = STATE_FILE.with_name(f".{STATE_FILE.name}.{uuid4().hex}.tmp")
    try:
        with tmp.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(validated.model_dump_json(indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(8):
            try:
                os.replace(tmp, STATE_FILE)
                break
            except OSError as exc:
                if attempt == 7:
                    raise ProjectPersistenceError(f"Could not atomically commit project state at {STATE_FILE}.") from exc
                time.sleep(0.05 * (attempt + 1))
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
