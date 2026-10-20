"""Conservative hardware checks before any model download or training run."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

MIN_VRAM_MIB = 8192
MIN_RAM_GIB = 16
MIN_FREE_GIB = 30


def total_ram_bytes() -> int:
    if sys.platform == "win32":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise OSError("GlobalMemoryStatusEx failed")
        return int(status.ullTotalPhys)
    return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))


def check_hardware() -> dict:
    try:
        memory_gib = round(total_ram_bytes() / (1024**3), 2)
    except (OSError, AttributeError) as exc:
        return {"ready": False, "blockers": [f"System RAM detection failed: {exc}"], "training_started": False}
    disk_gib = round(shutil.disk_usage(".").free / (1024**3), 2)
    gpu = {"available": False}
    if shutil.which("nvidia-smi"):
        result = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            name, vram, driver = [part.strip() for part in result.stdout.strip().splitlines()[0].split(",", 2)]
            gpu = {"available": True, "name": name, "vram_mib": int(vram.split()[0]), "driver": driver}
    blockers = []
    if not gpu["available"]:
        blockers.append("No supported NVIDIA GPU was detected by nvidia-smi.")
    elif gpu["vram_mib"] < MIN_VRAM_MIB:
        blockers.append(f"Detected {gpu['vram_mib']} MiB VRAM; this experiment conservatively requires {MIN_VRAM_MIB} MiB free-capable device memory.")
    if memory_gib < MIN_RAM_GIB:
        blockers.append(f"System RAM is {memory_gib} GiB; minimum configured threshold is {MIN_RAM_GIB} GiB.")
    if disk_gib < MIN_FREE_GIB:
        blockers.append(f"Free disk is {disk_gib} GiB; minimum configured threshold is {MIN_FREE_GIB} GiB.")
    return {"ready": not blockers, "gpu": gpu, "system_ram_gib": memory_gib, "free_disk_gib": disk_gib,
              "thresholds": {"vram_mib": MIN_VRAM_MIB, "ram_gib": MIN_RAM_GIB, "free_disk_gib": MIN_FREE_GIB},
              "blockers": blockers, "training_started": False,
              "note": "Preflight is conservative; it does not establish CUDA/PyTorch compatibility or guarantee training fits."}


def main() -> int:
    report = check_hardware()
    print(json.dumps(report, indent=2))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
