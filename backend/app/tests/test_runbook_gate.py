import pytest

from app.engines.runbook_gate import RunbookGateBlocked, evaluate_gate


def _steps(*spec):
    """spec: (title, required, status)"""
    return [
        {"id": i + 1, "seq": i + 1, "title": t, "required": r, "status": s}
        for i, (t, r, s) in enumerate(spec)
    ]


def test_gate_blocks_when_required_pending():
    steps = _steps(
        ("备份已完成", True, "success"),
        ("数据源就绪", True, "pending"),
        ("通知下游", False, "skipped"),
    )
    gate = evaluate_gate(steps)
    assert not gate["can_start"]
    assert gate["counts"]["required_done"] == 1
    assert gate["counts"]["required"] == 2
    assert "数据源就绪" in " ".join(gate["reasons"])
    assert [s["title"] for s in gate["blocking_steps"]] == ["数据源就绪"]


def test_gate_blocks_on_required_failure_even_if_others_done():
    steps = _steps(
        ("备份已完成", True, "failed"),
        ("数据源就绪", True, "success"),
    )
    gate = evaluate_gate(steps)
    assert not gate["can_start"]
    assert "备份已完成" in " ".join(gate["reasons"])


def test_gate_blocks_required_skipped():
    steps = _steps(("备份已完成", True, "skipped"))
    gate = evaluate_gate(steps)
    assert not gate["can_start"]
    assert "必做步骤不可跳过" in " ".join(gate["reasons"])


def test_gate_allows_when_all_required_success_and_optional_skipped():
    steps = _steps(
        ("备份已完成", True, "success"),
        ("数据源就绪", True, "success"),
        ("通知下游", False, "skipped"),
    )
    gate = evaluate_gate(steps)
    assert gate["can_start"]
    assert gate["reasons"] == []
    assert gate["consistent"]
    c = gate["counts"]
    assert (c["success"], c["failed"], c["skipped"], c["pending"]) == (2, 0, 1, 0)
    assert c["total"] == 3
    assert c["optional_skipped"] == c["skipped"] == 1


def test_gate_blocks_empty_runbook():
    gate = evaluate_gate([])
    assert not gate["can_start"]
    assert "尚未定义任何步骤" in " ".join(gate["reasons"])


def test_gate_detects_count_mismatch():
    steps = _steps(
        ("备份已完成", True, "success"),
        ("数据源就绪", True, "bogus"),
    )
    gate = evaluate_gate(steps)
    assert not gate["can_start"]
    assert not gate["consistent"]


def test_gate_blocked_exception_payload():
    gate = evaluate_gate(_steps(("备份已完成", True, "pending")))
    exc = RunbookGateBlocked({**gate, "batch_no": "RB-20260101-0001", "batch_status": "blocked"})
    payload = exc.payload()
    assert payload["decision"] == "blocked"
    assert payload["batch_no"] == "RB-20260101-0001"
    assert payload["reasons"]
