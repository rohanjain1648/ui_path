from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import InvoiceException, ExceptionStatus, Invoice, InvoiceStatus
from backend.services.claude_extraction import recommend_exception_resolution
from backend.services.exception_engine import get_sla_status

router = APIRouter()


class ExceptionResolvePayload(BaseModel):
    resolution_notes: str
    resolved_by: str
    action: str  # "approve", "reject", "request_credit_note", "amend_po", "vendor_query"


@router.get("/", summary="List open exceptions")
def list_exceptions(
    status: Optional[str] = None,
    assigned_to: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    q = db.query(InvoiceException)
    if status:
        q = q.filter(InvoiceException.status == status)
    if assigned_to:
        q = q.filter(InvoiceException.assigned_to == assigned_to)

    exceptions = q.order_by(InvoiceException.created_at.desc()).limit(limit).all()

    result = []
    for exc in exceptions:
        sla = get_sla_status(exc)
        result.append({
            "id": exc.id,
            "invoice_id": exc.invoice_id,
            "exception_type": exc.exception_type,
            "description": exc.description,
            "ai_recommendation": exc.ai_recommendation,
            "assigned_to": exc.assigned_to,
            "status": exc.status,
            "sla_status": sla,
            "sla_deadline": str(exc.sla_deadline) if exc.sla_deadline else None,
            "created_at": str(exc.created_at),
        })
    return result


@router.get("/{exception_id}", summary="Get exception with AI recommendation")
async def get_exception(exception_id: str, db: Session = Depends(get_db)):
    exc = _get_exc_or_404(exception_id, db)
    invoice = db.query(Invoice).filter(Invoice.id == exc.invoice_id).first()

    # Generate AI recommendation if not yet set
    if not exc.ai_recommendation and invoice:
        po_data = {"po_number": invoice.po_reference, "total_amount": None}
        exc.ai_recommendation = await recommend_exception_resolution(
            exception_type=str(exc.exception_type),
            invoice_data={
                "invoice_number": invoice.invoice_number,
                "vendor_name": invoice.vendor_name,
                "total_amount": invoice.total_amount,
                "currency": invoice.currency,
                "po_reference": invoice.po_reference,
            },
            po_data=po_data,
        )
        db.commit()

    return {
        "id": exc.id,
        "invoice_id": exc.invoice_id,
        "exception_type": exc.exception_type,
        "description": exc.description,
        "ai_recommendation": exc.ai_recommendation,
        "assigned_to": exc.assigned_to,
        "status": exc.status,
        "sla_status": get_sla_status(exc),
        "sla_deadline": str(exc.sla_deadline) if exc.sla_deadline else None,
        "resolution_notes": exc.resolution_notes,
        "created_at": str(exc.created_at),
        "resolved_at": str(exc.resolved_at) if exc.resolved_at else None,
    }


@router.post("/{exception_id}/resolve", summary="Resolve an AP exception")
def resolve_exception(
    exception_id: str,
    payload: ExceptionResolvePayload,
    db: Session = Depends(get_db),
):
    """
    UiPath BPMN Human Task: AP team member resolves an exception.
    Triggers downstream invoice status update based on action taken.
    """
    exc = _get_exc_or_404(exception_id, db)
    if exc.status == ExceptionStatus.RESOLVED:
        raise HTTPException(400, "Exception already resolved")

    exc.status = ExceptionStatus.RESOLVED
    exc.resolution_notes = f"[{payload.resolved_by}] {payload.action}: {payload.resolution_notes}"
    exc.resolved_at = datetime.now(timezone.utc)
    db.commit()

    # Update parent invoice status if all exceptions for this invoice are resolved
    open_exceptions = (
        db.query(InvoiceException)
        .filter(
            InvoiceException.invoice_id == exc.invoice_id,
            InvoiceException.status != ExceptionStatus.RESOLVED,
        )
        .count()
    )

    invoice = db.query(Invoice).filter(Invoice.id == exc.invoice_id).first()
    if invoice and open_exceptions == 0:
        if payload.action == "approve":
            invoice.status = InvoiceStatus.APPROVED
        elif payload.action == "reject":
            invoice.status = InvoiceStatus.REJECTED
        else:
            invoice.status = InvoiceStatus.EXCEPTION
        db.commit()

    return {
        "exception_id": exception_id,
        "status": "resolved",
        "invoice_status": invoice.status if invoice else None,
        "remaining_exceptions": open_exceptions,
    }


@router.post("/{exception_id}/escalate", summary="Escalate exception to next level")
def escalate_exception(exception_id: str, reason: str, db: Session = Depends(get_db)):
    exc = _get_exc_or_404(exception_id, db)
    exc.status = ExceptionStatus.ESCALATED
    exc.resolution_notes = f"ESCALATED: {reason}"
    db.commit()
    return {"exception_id": exception_id, "status": "escalated"}


def _get_exc_or_404(exception_id: str, db: Session) -> InvoiceException:
    exc = db.query(InvoiceException).filter(InvoiceException.id == exception_id).first()
    if not exc:
        raise HTTPException(404, f"Exception {exception_id} not found")
    return exc
