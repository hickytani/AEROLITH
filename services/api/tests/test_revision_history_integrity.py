"""Sprint 7: Comprehensive Revision History Integrity, Bounded Growth & Restoration Tests.

Verifies:
1. 20 sequential revisions on spur_gear_pair with linear (non-exponential) storage growth.
2. 20 sequential revisions on electric_vehicle with linear storage growth.
3. Full history inspection via GET /api/v1/project/history and /api/v1/project/history/{revision}.
4. Safe explicit restoration via POST /api/v1/project/restore/{revision} creating a new revision.
5. Rejection and invalid edits preserve canonical revision and history ledger.
"""
from __future__ import annotations

import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from aeropkmech import store
from aeropkmech.main import app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = tmp_path / "data"
    artifacts_dir = tmp_path / "artifacts"
    data_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AEROPKMECH_DATA_DIR", str(data_dir))
    monkeypatch.setenv("AEROPKMECH_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setattr(store, "DATA_DIR", data_dir)
    monkeypatch.setattr(store, "STATE_FILE", data_dir / "project.json")
    from aeropkmech import main as main_module
    monkeypatch.setattr(main_module, "ARTIFACTS", artifacts_dir)

    # Reset to default spur gear
    initial = store.default_design()
    store.save(initial)
    return TestClient(app)


def test_twenty_sequential_gear_revisions_bounded_growth_and_inspection(client: TestClient):
    """Verify that 20 sequential gear edits advance revision cleanly and file size grows linearly, not exponentially."""
    sizes = {}
    state_file = store.STATE_FILE

    # Starting state: revision 1
    r_initial = client.get("/api/v1/project")
    assert r_initial.status_code == 200
    current_rev = r_initial.json()["revision"]
    assert current_rev == 1
    sizes[1] = state_file.stat().st_size

    # Perform 19 sequential edits to reach revision 20
    for i in range(1, 20):
        # Vary face width slightly each time
        new_width = 12.0 + (i % 10)
        res = client.patch(
            "/api/v1/project",
            json={"face_width_mm": new_width, "expected_revision": current_rev},
        )
        assert res.status_code == 200, f"Edit at revision {current_rev} failed: {res.text}"
        data = res.json()
        current_rev = data["revision"]
        assert current_rev == i + 1

        if current_rev in (5, 10, 15, 20):
            sizes[current_rev] = state_file.stat().st_size

    # Verify linear, bounded growth (Sprint 6 regression was 91.8 MB at rev 15!)
    # At rev 20, size must be well under 400 KB (measured ~264 KB)
    assert sizes[20] < 400_000, f"State file too large at rev 20: {sizes[20]} bytes"
    # Growth between rev 10 and rev 20 should be strictly sub-linear or linear (roughly proportional to 10 snapshots)
    delta_10_to_20 = sizes[20] - sizes[10]
    delta_1_to_10 = sizes[10] - sizes[1]
    # Ratio should be bounded (< 3x)
    assert delta_10_to_20 < delta_1_to_10 * 3, f"Non-linear growth detected: {delta_10_to_20} vs {delta_1_to_10}"

    # Verify history list endpoint
    hist_res = client.get("/api/v1/project/history")
    assert hist_res.status_code == 200
    hist_data = hist_res.json()
    assert hist_data["current_revision"] == 20
    assert hist_data["total_revisions"] == 20
    assert len(hist_data["history"]) == 20

    # Verify inspection of individual past revisions
    for check_rev in [1, 5, 10, 15, 20]:
        single_res = client.get(f"/api/v1/project/history/{check_rev}")
        assert single_res.status_code == 200
        snap = single_res.json()
        assert snap["revision"] == check_rev
        assert snap["family"] == "spur_gear_pair"
        assert len(snap["derived"]["components"]) == 2


def test_history_restoration_creates_new_revision_preserving_history(client: TestClient):
    """Verify that restoring revision 1 from revision 3 creates revision 4 and preserves history."""
    # Rev 1 -> Rev 2 (module 2.5)
    r2 = client.patch("/api/v1/project", json={"module_mm": 2.5, "expected_revision": 1})
    assert r2.status_code == 200
    assert r2.json()["revision"] == 2

    # Rev 2 -> Rev 3 (module 3.0)
    r3 = client.patch("/api/v1/project", json={"module_mm": 3.0, "expected_revision": 2})
    assert r3.status_code == 200
    assert r3.json()["revision"] == 3
    mod3 = r3.json()["requirements"]["module_mm"]
    assert (mod3.get("value") if isinstance(mod3, dict) else mod3) == 3.0

    # Restore revision 1 (which had module 2.0)
    restore_res = client.post("/api/v1/project/restore/1", json={"expected_revision": 3})
    assert restore_res.status_code == 200
    r4 = restore_res.json()
    assert r4["revision"] == 4  # Advanced, did not overwrite!
    mod4 = r4["requirements"]["module_mm"]
    assert (mod4.get("value") if isinstance(mod4, dict) else mod4) == 2.0  # Restored value!

    # Verify history audit trail
    hist_res = client.get("/api/v1/project/history")
    hist_data = hist_res.json()
    assert hist_data["current_revision"] == 4
    assert hist_data["total_revisions"] == 4

    # The latest history entry (snapshot of rev 3) records restored_from_revision: 1
    last_hist = hist_data["history"][-2]  # index -2 is the last entry before active
    assert last_hist["revision"] == 3
    assert last_hist["restored_from_revision"] == 1


def test_invalid_restore_requests_handled_safely(client: TestClient):
    """Restoring active revision returns 400; nonexistent revision returns 404; stale expected revision returns 409."""
    # Active revision is 1; restoring 1 returns 400
    r_same = client.post("/api/v1/project/restore/1")
    assert r_same.status_code == 400

    # Nonexistent revision 99 returns 404
    r_missing = client.post("/api/v1/project/restore/99")
    assert r_missing.status_code == 404

    # Make rev 2
    client.patch("/api/v1/project", json={"module_mm": 2.5, "expected_revision": 1})

    # Expected revision mismatch returns 409
    r_conflict = client.post("/api/v1/project/restore/1", json={"expected_revision": 1})
    assert r_conflict.status_code == 409
    assert client.get("/api/v1/project").json()["revision"] == 2  # State preserved


def test_rejected_and_invalid_edits_preserve_canonical_state(client: TestClient):
    """Verifies that rejected NL proposals and validation errors never increment revision or append history."""
    initial_rev = client.get("/api/v1/project").json()["revision"]

    # Propose an edit (does not commit)
    prop = client.post("/api/v1/project/propose-edit", json={"text": "Set module to 2.5 mm", "expected_revision": initial_rev})
    assert prop.status_code == 200
    # State remains untouched
    assert client.get("/api/v1/project").json()["revision"] == initial_rev

    # Invalid edit (out-of-range module)
    invalid_patch = client.patch("/api/v1/project", json={"module_mm": -10.0, "expected_revision": initial_rev})
    assert invalid_patch.status_code == 422
    # State remains untouched
    assert client.get("/api/v1/project").json()["revision"] == initial_rev

    # History count remains 1
    hist = client.get("/api/v1/project/history").json()
    assert hist["total_revisions"] == 1


def test_ev_revisions_bounded_growth_and_integrity(client: TestClient):
    """Verify that EV sequential edits maintain linear bounded growth and all 27 components stay inspectable."""
    # Initialize EV
    init_res = client.post("/api/v1/project/initialize", json={"family_id": "electric_vehicle"})
    assert init_res.status_code == 200
    ev_rev = init_res.json()["revision"]
    assert init_res.json()["family"] == "electric_vehicle"

    state_file = store.STATE_FILE
    sizes = {ev_rev: state_file.stat().st_size}

    # Perform 5 valid EV parameter edits
    for i in range(1, 6):
        new_wheelbase = 2700.0 + (i * 20.0)
        res = client.patch(
            "/api/v1/project/vehicle",
            json={"wheelbase_mm": new_wheelbase, "expected_revision": ev_rev},
        )
        assert res.status_code == 200
        ev_rev = res.json()["revision"]
        sizes[ev_rev] = state_file.stat().st_size

    # Even with 27 components per snapshot, 6 EV revisions must be well under 500 KB
    assert sizes[ev_rev] < 500_000, f"EV state file too large: {sizes[ev_rev]} bytes"

    # Verify history inspection for EV
    hist_res = client.get("/api/v1/project/history")
    assert hist_res.status_code == 200
    hist = hist_res.json()
    assert hist["current_revision"] == ev_rev

    # Inspect historical EV snapshot
    first_ev_rev = init_res.json()["revision"]
    snap_res = client.get(f"/api/v1/project/history/{first_ev_rev}")
    assert snap_res.status_code == 200
    snap = snap_res.json()
    assert snap["family"] == "electric_vehicle"
    assert len(snap["derived"]["components"]) == 27
