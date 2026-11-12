from fastapi import APIRouter, HTTPException

from app.engines.runbook_gate import RunbookGateBlocked
from app.schemas.entities import RunbookStepBody, RunbookStepStatusBody
from app.services import orchestrate_service as svc

router = APIRouter(tags=["runbook"])


@router.get("/runbook")
def get_runbook():
    return svc.runbook_state_standalone()


@router.get("/runbook/gate")
def get_gate():
    state = svc.runbook_state_standalone()
    return state["gate"]


@router.post("/runbook/steps")
def add_step(body: RunbookStepBody):
    return svc.add_step(body.title.strip(), body.required)


@router.patch("/runbook/steps/{step_id}")
def patch_step(step_id: int, body: RunbookStepStatusBody):
    try:
        return svc.set_step_status(step_id, body.status, body.note)
    except LookupError:
        raise HTTPException(404, "step not found") from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.delete("/runbook/steps/{step_id}")
def delete_step(step_id: int):
    svc.delete_step(step_id)
    return {"deleted": step_id}


@router.post("/orchestrations")
def start_orchestration():
    try:
        return svc.start_orchestration()
    except RunbookGateBlocked as exc:
        raise HTTPException(409, exc.payload()) from None
