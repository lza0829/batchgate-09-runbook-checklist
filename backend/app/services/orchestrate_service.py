from __future__ import annotations

from typing import Any

from app.config import FIXTURES_DIR
from app.db import connect
from app.engines.dependency import ready_by_upstream_success, topological_layers
from app.engines.job_runner import run_fixture_job
from app.engines.runbook_gate import RunbookGateBlocked, STATUS_LABELS, evaluate_gate
from app.repositories import jobs as jobs_repo
from app.repositories import orchestrations as orch_repo
from app.repositories import runbook as runbook_repo
from app.repositories import watermarks as wm_repo

VALID_STEP_STATUSES = ("pending", "success", "failed", "skipped")


def dashboard_stats() -> dict[str, Any]:
    conn = connect()
    try:
        stats = {
            "job_count": conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"],
            "enabled_jobs": conn.execute(
                "SELECT COUNT(*) c FROM jobs WHERE enabled=1"
            ).fetchone()["c"],
            "orchestration_count": conn.execute(
                "SELECT COUNT(*) c FROM orchestrations"
            ).fetchone()["c"],
            "attempt_count": conn.execute(
                "SELECT COUNT(*) c FROM job_attempts"
            ).fetchone()["c"],
            "watermarked_jobs": conn.execute(
                "SELECT COUNT(*) c FROM watermarks WHERE watermark_ts IS NOT NULL"
            ).fetchone()["c"],
        }
        gate = runbook_state(conn)["gate"]
        stats["runbook_can_start"] = gate["can_start"]
        stats["runbook_counts"] = gate["counts"]
        stats["runbook_reasons"] = gate["reasons"]
        return stats
    finally:
        conn.close()


def _snapshot(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": s["id"],
            "seq": s["seq"],
            "title": s["title"],
            "required": bool(s["required"]),
            "status": s["status"],
            "note": s.get("note", ""),
            "updated_at": s.get("updated_at"),
        }
        for s in steps
    ]


def runbook_state(conn) -> dict[str, Any]:
    steps = runbook_repo.list_steps(conn)
    gate = evaluate_gate(steps)
    return {
        "steps": steps,
        "label_map": STATUS_LABELS,
        "gate": gate,
        "events": runbook_repo.list_events(conn),
        "batches": runbook_repo.list_batches(conn),
    }


def runbook_state_standalone() -> dict[str, Any]:
    conn = connect()
    try:
        return runbook_state(conn)
    finally:
        conn.close()


def add_step(title: str, required: bool) -> dict[str, Any]:
    conn = connect()
    try:
        step = runbook_repo.add_step(conn, title, required)
        conn.commit()
        return step
    finally:
        conn.close()


def set_step_status(
    step_id: int, status: str, note: str = ""
) -> dict[str, Any]:
    if status not in VALID_STEP_STATUSES:
        raise ValueError(f"invalid status: {status}")
    conn = connect()
    try:
        step = runbook_repo.get_step(conn, step_id)
        if not step:
            raise LookupError("step not found")
        from_status = step["status"]
        if status == "skipped" and step["required"]:
            raise ValueError("必做步骤不可跳过，请标记为成功或失败")
        updated = runbook_repo.update_step_status(conn, step_id, status, note)
        if from_status != status:
            runbook_repo.record_event(
                conn,
                step=step,
                from_status=from_status,
                to_status=status,
                batch_id=None,
                note=note,
            )
        conn.commit()
        return updated
    finally:
        conn.close()


def delete_step(step_id: int) -> None:
    conn = connect()
    try:
        runbook_repo.delete_step(conn, step_id)
        conn.commit()
    finally:
        conn.close()


def _run_jobs(conn, orch_id: int) -> dict[str, Any]:
    jobs = [j for j in jobs_repo.list_jobs(conn) if j["enabled"]]
    success_names: set[str] = set()
    skipped = 0
    failed = 0
    succeeded = 0
    layers = topological_layers(jobs)

    for layer in layers:
        for job in layer:
            ready, reason = ready_by_upstream_success(job["depends_on"], success_names)
            if not ready:
                orch_repo.insert_attempt(
                    conn,
                    orchestration_id=orch_id,
                    job_id=job["id"],
                    attempt_no=1,
                    status="skipped_dep",
                    detail={"reason": reason},
                )
                skipped += 1
                continue
            try:
                result = run_fixture_job(FIXTURES_DIR / job["fixture_path"])
                orch_repo.insert_attempt(
                    conn,
                    orchestration_id=orch_id,
                    job_id=job["id"],
                    attempt_no=1,
                    status="success",
                    detail=result,
                )
                wm_repo.set_watermark(
                    conn, job["id"], result["watermark_ts"], result["artifact_rows"]
                )
                success_names.add(job["name"])
                succeeded += 1
            except Exception as exc:  # noqa: BLE001
                orch_repo.insert_attempt(
                    conn,
                    orchestration_id=orch_id,
                    job_id=job["id"],
                    attempt_no=1,
                    status="failed",
                    detail={"error": str(exc)},
                )
                failed += 1

    attempts = orch_repo.list_attempts(conn, orch_id)
    return {
        "orchestration_id": orch_id,
        "job_total": len(jobs),
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
        "attempt_count": len(attempts),
        "watermarked_jobs": conn.execute(
            "SELECT COUNT(*) c FROM watermarks WHERE watermark_ts IS NOT NULL"
        ).fetchone()["c"],
        "layer_count": len(layers),
    }


def start_orchestration() -> dict[str, Any]:
    """Gate the runbook checklist first; only a passing gate starts the run.

    Refusals are recorded as a ``blocked`` runbook batch (snapshot + reasons)
    but never create an orchestration.  Allowed starts record an ``allowed``
    batch and stamp the orchestration with the batch id + batch no so the run
    can be traced back to the step snapshot in force at the time.
    """
    conn = connect()
    try:
        steps = runbook_repo.list_steps(conn)
        gate = evaluate_gate(steps)
        snapshot = _snapshot(steps)

        if not gate["can_start"]:
            batch = runbook_repo.create_batch(
                conn,
                decision="blocked",
                snapshot=snapshot,
                reasons=gate["reasons"],
                orchestration_id=None,
            )
            conn.commit()
            blocked = RunbookGateBlocked(
                {
                    **gate,
                    "batch_id": batch["id"],
                    "batch_no": batch["batch_no"],
                    "batch_status": "blocked",
                    "snapshot": snapshot,
                }
            )
            raise blocked

        batch = runbook_repo.create_batch(
            conn,
            decision="allowed",
            snapshot=snapshot,
            reasons=[],
            orchestration_id=None,
        )
        orch_id = orch_repo.create_orchestration(
            conn,
            runbook_batch_id=batch["id"],
            runbook_batch_no=batch["batch_no"],
        )
        runbook_repo.attach_batch_orchestration(conn, batch["id"], orch_id)

        report = _run_jobs(conn, orch_id)
        report["runbook"] = {
            "batch_id": batch["id"],
            "batch_no": batch["batch_no"],
            "decision": "allowed",
            "snapshot": snapshot,
            "counts": gate["counts"],
            "consistent": gate["consistent"],
        }
        status = "ok" if report["failed"] == 0 else "partial"
        orch_repo.finish_orchestration(conn, orch_id, status, report)
        conn.commit()
        return orch_repo.get_orchestration(conn, orch_id) or report
    finally:
        conn.close()
