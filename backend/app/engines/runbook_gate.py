"""Pre-orchestration runbook gate.

The runbook is an ordered checklist owned by the control plane.  A required
step must reach ``success`` before an orchestration may start; optional steps
may be skipped.  Step execution results are runbook state, never business
outputs (watermarks / attempt rows stay untouched by this module).
"""

from __future__ import annotations

from typing import Any

STEP_STATUSES = ("pending", "success", "failed", "skipped")
STATUS_LABELS = {
    "pending": "待办",
    "success": "成功",
    "failed": "失败",
    "skipped": "跳过",
}


class RunbookGateBlocked(Exception):
    """Raised when an orchestration is refused because the runbook gate is closed."""

    def __init__(self, gate: dict[str, Any]):
        self.gate = gate
        super().__init__("; ".join(gate.get("reasons") or ["runbook gate blocked"]))

    def payload(self) -> dict[str, Any]:
        return {
            "decision": "blocked",
            "batch_no": self.gate.get("batch_no"),
            "batch_status": self.gate.get("batch_status"),
            "reasons": self.gate.get("reasons", []),
            "gate": self.gate,
        }


def _step_brief(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": step.get("id"),
        "seq": step.get("seq"),
        "title": step.get("title"),
        "status": step.get("status"),
    }


def evaluate_gate(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate the checklist and return counts + refusal reasons.

    The counts are recomputed straight from the step list; ``consistent``
    asserts that success / failed / optional-skipped / pending add up to the
    list length and that no required step was skipped.
    """
    counts = {
        "total": len(steps),
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "pending": 0,
        "required": 0,
        "required_done": 0,
        "optional": 0,
        "optional_skipped": 0,
    }
    unknown: list[dict[str, Any]] = []
    required_pending: list[dict[str, Any]] = []
    required_failed: list[dict[str, Any]] = []
    required_skipped: list[dict[str, Any]] = []

    for step in steps:
        status = step.get("status")
        if status in STATUS_LABELS:
            counts[status] += 1
        else:
            unknown.append(step)
        if step.get("required"):
            counts["required"] += 1
            if status == "success":
                counts["required_done"] += 1
            elif status == "pending":
                required_pending.append(step)
            elif status == "failed":
                required_failed.append(step)
            elif status == "skipped":
                required_skipped.append(step)
        else:
            counts["optional"] += 1
            if status == "skipped":
                counts["optional_skipped"] += 1

    status_sum = counts["success"] + counts["failed"] + counts["skipped"] + counts["pending"]
    counts_consistent = (
        status_sum == counts["total"]
        and not unknown
        and counts["skipped"] == counts["optional_skipped"]
    )

    reasons: list[str] = []
    if not steps:
        reasons.append("尚未定义任何步骤，待办队列为空")
    if unknown:
        reasons.append("步骤状态非法：" + "、".join(str(s.get("title")) for s in unknown))
    if required_skipped:
        reasons.append(
            "必做步骤不可跳过：" + "、".join(str(s.get("title")) for s in required_skipped)
        )
    if required_pending:
        reasons.append(
            "必做步骤未完成：" + "、".join(str(s.get("title")) for s in required_pending)
        )
    if required_failed:
        reasons.append(
            "必做步骤失败：" + "、".join(str(s.get("title")) for s in required_failed)
        )
    if not counts_consistent:
        reasons.append(
            "步骤统计与步骤列表不一致："
            f"success+failed+skipped+pending={status_sum}，total={counts['total']}"
        )

    can_start = (
        bool(steps)
        and counts_consistent
        and counts["required_done"] == counts["required"]
    )

    blocking = required_pending + required_failed + required_skipped
    return {
        "can_start": can_start,
        "reasons": reasons,
        "consistent": counts_consistent,
        "counts": counts,
        "blocking_steps": [_step_brief(s) for s in blocking],
    }
