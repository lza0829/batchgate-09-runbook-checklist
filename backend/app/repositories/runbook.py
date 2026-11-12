from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import sqlite3

STATUS_LABELS = {"pending": "待办", "success": "成功", "failed": "失败", "skipped": "跳过"}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _step_row(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    d["required"] = bool(d["required"])
    return d


def list_steps(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, seq, title, required, status, note, updated_at FROM runbook_steps ORDER BY seq, id"
    ).fetchall()
    return [_step_row(r) for r in rows]


def get_step(conn: sqlite3.Connection, step_id: int) -> dict[str, Any] | None:
    r = conn.execute(
        "SELECT id, seq, title, required, status, note, updated_at FROM runbook_steps WHERE id=?",
        (step_id,),
    ).fetchone()
    return _step_row(r) if r else None


def add_step(conn: sqlite3.Connection, title: str, required: bool) -> dict[str, Any]:
    seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 s FROM runbook_steps").fetchone()["s"]
    cur = conn.execute(
        "INSERT INTO runbook_steps(seq, title, required, status, note, updated_at) VALUES (?,?,?,?,?,?)",
        (seq, title, int(required), "pending", "", _now()),
    )
    return get_step(conn, int(cur.lastrowid))  # type: ignore[return-value]


def update_step_status(
    conn: sqlite3.Connection,
    step_id: int,
    status: str,
    note: str = "",
) -> dict[str, Any]:
    conn.execute(
        "UPDATE runbook_steps SET status=?, note=?, updated_at=? WHERE id=?",
        (status, note, _now(), step_id),
    )
    return get_step(conn, step_id)  # type: ignore[return-value]


def delete_step(conn: sqlite3.Connection, step_id: int) -> None:
    conn.execute("DELETE FROM runbook_steps WHERE id=?", (step_id,))


def reset_steps(conn: sqlite3.Connection, steps: list[tuple[str, bool]]) -> None:
    conn.execute("DELETE FROM runbook_steps")
    for seq, (title, required) in enumerate(steps, start=1):
        conn.execute(
            "INSERT INTO runbook_steps(seq, title, required, status, note, updated_at) VALUES (?,?,?,?,?,?)",
            (seq, title, int(required), "pending", "", _now()),
        )


def record_event(
    conn: sqlite3.Connection,
    *,
    step: dict[str, Any],
    from_status: str,
    to_status: str,
    batch_id: int | None,
    note: str,
) -> None:
    conn.execute(
        """
        INSERT INTO runbook_step_events(step_id, seq, title, required, from_status, to_status, batch_id, note, created_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            step["id"],
            step["seq"],
            step["title"],
            int(step["required"]),
            from_status,
            to_status,
            batch_id,
            note,
            _now(),
        ),
    )


def list_events(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, step_id, seq, title, required, from_status, to_status, batch_id, note, created_at
        FROM runbook_step_events ORDER BY id DESC
        """
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["required"] = bool(d["required"])
        out.append(d)
    return out


def _next_batch_no(conn: sqlite3.Connection) -> str:
    prefix = "RB-" + datetime.now(timezone.utc).strftime("%Y%m%d") + "-"
    row = conn.execute(
        "SELECT batch_no FROM runbook_batches WHERE batch_no LIKE ? ORDER BY batch_no DESC LIMIT 1",
        (prefix + "%",),
    ).fetchone()
    n = int(row["batch_no"].rsplit("-", 1)[1]) + 1 if row else 1
    return f"{prefix}{n:04d}"


def create_batch(
    conn: sqlite3.Connection,
    *,
    decision: str,
    snapshot: list[dict[str, Any]],
    reasons: list[str],
    orchestration_id: int | None,
) -> dict[str, Any]:
    batch_no = _next_batch_no(conn)
    cur = conn.execute(
        """
        INSERT INTO runbook_batches(batch_no, decision, orchestration_id, snapshot_json, reasons_json, created_at)
        VALUES (?,?,?,?,?,?)
        """,
        (
            batch_no,
            decision,
            orchestration_id,
            json.dumps(snapshot, ensure_ascii=False),
            json.dumps(reasons, ensure_ascii=False),
            _now(),
        ),
    )
    return get_batch(conn, int(cur.lastrowid))  # type: ignore[return-value]


def attach_batch_orchestration(
    conn: sqlite3.Connection, batch_id: int, orchestration_id: int
) -> None:
    conn.execute(
        "UPDATE runbook_batches SET orchestration_id=? WHERE id=?",
        (orchestration_id, batch_id),
    )


def _batch_row(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    d["snapshot"] = json.loads(d.pop("snapshot_json"))
    d["reasons"] = json.loads(d.pop("reasons_json"))
    return d


def get_batch(conn: sqlite3.Connection, batch_id: int) -> dict[str, Any] | None:
    r = conn.execute(
        """
        SELECT id, batch_no, decision, orchestration_id, snapshot_json, reasons_json, created_at
        FROM runbook_batches WHERE id=?
        """,
        (batch_id,),
    ).fetchone()
    return _batch_row(r) if r else None


def list_batches(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, batch_no, decision, orchestration_id, snapshot_json, reasons_json, created_at
        FROM runbook_batches ORDER BY id DESC
        """
    ).fetchall()
    return [_batch_row(r) for r in rows]
