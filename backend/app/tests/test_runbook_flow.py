"""End-to-end runbook gate tests against a temp SQLite DB (no HTTP client needed)."""

from __future__ import annotations

import json

import pytest

from app import seed
from app import db as db_module
from app.engines.runbook_gate import RunbookGateBlocked
from app.repositories import orchestrations as orch_repo
from app.repositories import runbook as runbook_repo
from app.services import orchestrate_service as svc


@pytest.fixture
def bound_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "app.db")
    monkeypatch.setattr(db_module, "DATA_DIR", tmp_path)
    seed.init_db()
    yield


def test_blocked_start_records_batch_without_orchestration(bound_db):
    conn = db_module.connect()
    try:
        runbook_repo.reset_steps(conn, [("备份确认", True), ("通知下游", False)])
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(RunbookGateBlocked) as ex:
        svc.start_orchestration()
    gate = ex.value.gate
    assert gate["can_start"] is False
    assert gate["reasons"]

    conn = db_module.connect()
    try:
        assert conn.execute("SELECT COUNT(*) c FROM orchestrations").fetchone()["c"] == 0
        batches = runbook_repo.list_batches(conn)
        assert len(batches) == 1
        assert batches[0]["decision"] == "blocked"
        assert batches[0]["orchestration_id"] is None
        assert batches[0]["reasons"]
        snap_statuses = [s["status"] for s in batches[0]["snapshot"]]
        assert snap_statuses == ["pending", "pending"]
    finally:
        conn.close()


def test_required_step_cannot_be_skipped(bound_db):
    conn = db_module.connect()
    try:
        steps = runbook_repo.list_steps(conn)
        step_id = steps[0]["id"]
    finally:
        conn.close()
    with pytest.raises(ValueError, match="必做步骤不可跳过"):
        svc.set_step_status(step_id, "skipped")


def test_allowed_start_links_batch_snapshot(bound_db):
    conn = db_module.connect()
    try:
        runbook_repo.reset_steps(conn, [("备份确认", True), ("通知下游", False)])
        for step in runbook_repo.list_steps(conn):
            status = "success" if step["required"] else "skipped"
            runbook_repo.update_step_status(conn, step["id"], status, "done")
        conn.commit()
    finally:
        conn.close()

    result = svc.start_orchestration()
    assert result["status"] == "ok"

    conn = db_module.connect()
    try:
        orch = orch_repo.get_orchestration(conn, result["id"])
        assert orch["runbook_batch_id"] is not None
        assert orch["runbook_batch_no"].startswith("RB-")
        batch = runbook_repo.get_batch(conn, orch["runbook_batch_id"])
        assert batch["decision"] == "allowed"
        assert batch["orchestration_id"] == orch["id"]
        assert [s["status"] for s in batch["snapshot"]] == ["success", "skipped"]
        assert [s["title"] for s in batch["snapshot"]] == ["备份确认", "通知下游"]
        report = orch["report"]
        assert report["runbook"]["batch_no"] == batch["batch_no"]
        assert report["runbook"]["counts"]["success"] == 1
        assert report["runbook"]["counts"]["skipped"] == 1
        assert report["runbook"]["counts"]["total"] == 2
        assert report["attempt_count"] == 3
    finally:
        conn.close()


def test_failed_step_blocks_then_fixing_allows(bound_db):
    with pytest.raises(RunbookGateBlocked):
        svc.start_orchestration()  # seeded steps all pending

    conn = db_module.connect()
    try:
        steps = runbook_repo.list_steps(conn)
        first = next(s for s in steps if s["required"])
    finally:
        conn.close()
    svc.set_step_status(first["id"], "failed", "备份校验不通过")

    with pytest.raises(RunbookGateBlocked):
        svc.start_orchestration()

    conn = db_module.connect()
    try:
        for step in runbook_repo.list_steps(conn):
            new_status = "success" if step["required"] else "skipped"
            runbook_repo.update_step_status(conn, step["id"], new_status, "")
        conn.commit()
        gate = svc.runbook_state(conn)["gate"]
        assert gate["can_start"]
        assert gate["counts"]["failed"] == 0
        assert gate["counts"]["success"] == gate["counts"]["required"]
    finally:
        conn.close()

    result = svc.start_orchestration()
    assert result["status"] == "ok"
    assert result["report"]["runbook"]["decision"] == "allowed"
