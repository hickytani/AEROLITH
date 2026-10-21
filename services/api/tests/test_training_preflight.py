import importlib.util
from pathlib import Path
import subprocess
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[3] / "ml-training" / "scripts" / "preflight.py"
SPEC = importlib.util.spec_from_file_location("aeropkmech_training_preflight", SCRIPT)
preflight = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(preflight)


GIB = 1024**3


def _mock_telemetry(monkeypatch, *, ram=20 * GIB, available=10 * GIB, disk=100 * GIB, gpu_line=None):
    monkeypatch.setattr(preflight, "memory_bytes", lambda: (ram, available))
    monkeypatch.setattr(preflight.shutil, "disk_usage", lambda _path: SimpleNamespace(free=disk))
    monkeypatch.setattr(preflight.shutil, "which", lambda _name: "nvidia-smi")

    def run(*_args, **_kwargs):
        return subprocess.CompletedProcess("nvidia-smi", 0, gpu_line or "NVIDIA test, 8192 MiB, 8192 MiB, 555.0\n", "")

    monkeypatch.setattr(preflight.subprocess, "run", run)


def test_preflight_blocks_low_available_memory_before_any_model_load(monkeypatch):
    _mock_telemetry(monkeypatch, ram=15 * GIB, available=2 * GIB, gpu_line="NVIDIA test, 6144 MiB, 5500 MiB, 555.0\n")
    result = preflight.check_hardware()
    assert result["ready"] is False
    assert result["training_started"] is False
    assert any("available system RAM" in blocker for blocker in result["blockers"])
    assert any("System RAM is" in blocker for blocker in result["blockers"])
    assert any("VRAM" in blocker for blocker in result["blockers"])


def test_preflight_passes_only_when_every_configured_threshold_is_met(monkeypatch):
    _mock_telemetry(monkeypatch)
    result = preflight.check_hardware()
    assert result["ready"] is True
    assert result["blockers"] == []
    assert result["training_started"] is False


def test_preflight_fails_closed_on_gpu_timeout_or_malformed_telemetry(monkeypatch):
    _mock_telemetry(monkeypatch)
    monkeypatch.setattr(preflight.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("nvidia-smi", 10)))
    timed_out = preflight.check_hardware()
    assert timed_out["ready"] is False
    assert any("timed out" in blocker for blocker in timed_out["blockers"])

    _mock_telemetry(monkeypatch, gpu_line="malformed output\n")
    malformed = preflight.check_hardware()
    assert malformed["ready"] is False
    assert any("malformed GPU data" in blocker for blocker in malformed["blockers"])


def test_preflight_fails_closed_when_disk_capacity_cannot_be_read(monkeypatch):
    _mock_telemetry(monkeypatch)
    monkeypatch.setattr(preflight.shutil, "disk_usage", lambda _path: (_ for _ in ()).throw(OSError("hidden detail")))
    result = preflight.check_hardware()
    assert result["ready"] is False
    assert any("cannot be verified" in blocker for blocker in result["blockers"])
    assert all("hidden detail" not in blocker for blocker in result["blockers"])
