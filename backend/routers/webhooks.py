"""
Webhook receiver for UiPath Automation Cloud callbacks.

UiPath calls these endpoints when:
  - A BPMN process instance changes state
  - An Action Center human task is completed (approved/rejected)
  - A robot job finishes

Configure the webhook URL in UiPath Orchestrator:
  Settings → Webhooks → Add Webhook
  URL: https://your-public-url/api/webhooks/uipath
  Events: job.completed, task.completed
  Secret: value of UIPATH_WEBHOOK_SECRET in .env
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Invoice, InvoiceStatus, Approval, ApprovalStatus, InvoiceException, ExceptionStatus
from backend.services.uipath_service import validate_webhook_signature

router = APIRouter()


@router.post("/uipath", summary="Receive UiPath Orchestrator webhook events")
async def uipath_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Receives events from UiPath Automation Cloud.

    Supported event types:
      - job.completed       : BPMN process step finished
      - task.completed      : Action Center task resolved by human
      - task.comment.created: Comment added to a task
    """
    raw_body = await request.body()

    # Validate webhook signature
    sig = request.headers.get("x-uipath-signature", "")
    if not validate_webhook_signature(raw_body, sig):
        raise HTTPException(401, "Invalid webhook signature")

    payload = await request.json()
    event_type = payload.get("Type", payload.get("type", ""))

    # ── Action Center task completed (approval or exception resolved) ─────────
    if event_type in ("task.completed", "TaskCompleted"):
        return await _handle_task_completed(payload, db)

    # ── BPMN Job state change ─────────────────────────────────────────────────
    if event_type in ("job.completed", "job.faulted", "JobCompleted"):
        return await _handle_job_event(payload, db)

    # Unknown event — acknowledge but don't process
    return {"status": "acknowledged", "event": event_type}


async def _handle_task_completed(payload: dict, db: Session) -> dict:
    """
    Process a completed Action Center task.
    Task data contains invoice_id and the human's decision.
    """
    task_data = payload.get("TaskData", payload.get("data", {}))
    invoice_id = task_data.get("invoice_id")
    task_catalog = payload.get("TaskCatalogName", "")
    output = task_data.get("Output", task_data.get("output", {}))

    if not invoice_id:
        return {"status": "ignored", "reason": "No invoice_id in task data"}

    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        return {"status": "error", "reason": f"Invoice {invoice_id} not found"}

    # ── Approval task ─────────────────────────────────────────────────────────
    if "Approval" in task_catalog or "approval" in task_catalog.lower():
        approved = output.get("approved", output.get("decision", "").lower() == "approve")
        approver = output.get("completed_by", "UiPath Action Center")
        notes = output.get("notes", "Decision via UiPath Action Center")

        pending_approval = (
            db.query(Approval)
            .filter(Approval.invoice_id == invoice_id, Approval.status == ApprovalStatus.PENDING)
            .first()
        )
        if pending_approval:
            pending_approval.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
            pending_approval.notes = notes
            pending_approval.decided_at = datetime.now(timezone.utc)

        invoice.status = InvoiceStatus.APPROVED if approved else InvoiceStatus.REJECTED
        invoice.processing_notes = f"{'Approved' if approved else 'Rejected'} by {approver} via Action Center: {notes}"
        db.commit()

        return {
            "status": "processed",
            "invoice_id": invoice_id,
            "decision": "approved" if approved else "rejected",
        }

    # ── Exception resolution task ─────────────────────────────────────────────
    if "Exception" in task_catalog or "exception" in task_catalog.lower():
        action = output.get("action", "approve")
        resolved_by = output.get("completed_by", "UiPath Action Center")
        resolution_notes = output.get("resolution_notes", "Resolved via Action Center")

        open_exceptions = (
            db.query(InvoiceException)
            .filter(InvoiceException.invoice_id == invoice_id, InvoiceException.status == ExceptionStatus.OPEN)
            .all()
        )
        for exc in open_exceptions:
            exc.status = ExceptionStatus.RESOLVED
            exc.resolution_notes = f"[{resolved_by}] {action}: {resolution_notes}"
            exc.resolved_at = datetime.now(timezone.utc)

        if action == "approve":
            invoice.status = InvoiceStatus.APPROVED
        elif action == "reject":
            invoice.status = InvoiceStatus.REJECTED

        db.commit()
        return {"status": "processed", "invoice_id": invoice_id, "exceptions_resolved": len(open_exceptions)}

    return {"status": "ignored", "reason": f"Unknown task catalog: {task_catalog}"}


async def _handle_job_event(payload: dict, db: Session) -> dict:
    """Log BPMN job completion events."""
    job_key = payload.get("JobKey", "unknown")
    state = payload.get("State", payload.get("state", "unknown"))
    invoice_id = (payload.get("OutputArguments") or {}).get("invoice_id")

    if invoice_id and state == "Successful":
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if invoice:
            invoice.processing_notes = (
                (invoice.processing_notes or "") +
                f" | BPMN Job {job_key} completed successfully"
            )
            db.commit()

    return {"status": "acknowledged", "job_key": job_key, "state": state}


# ── Health check for webhook URL verification ─────────────────────────────────
@router.get("/uipath", summary="Webhook URL verification (GET)")
def webhook_verify():
    """UiPath may send a GET request to verify the webhook URL is reachable."""
    return {"status": "ok", "service": "IntelliFlow AP Webhook Receiver"}
