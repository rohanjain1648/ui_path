from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Approval, ApprovalStatus, Invoice, InvoiceStatus

router = APIRouter()


class ApprovalDecision(BaseModel):
    approved: bool
    notes: Optional[str] = None
    approver_name: Optional[str] = None


@router.get("/", summary="List pending approvals")
def list_approvals(
    approver_email: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Approval)
    if approver_email:
        q = q.filter(Approval.approver_email == approver_email)
    if status:
        q = q.filter(Approval.status == status)
    else:
        q = q.filter(Approval.status == ApprovalStatus.PENDING)

    approvals = q.order_by(Approval.created_at.asc()).all()
    result = []
    for a in approvals:
        invoice = db.query(Invoice).filter(Invoice.id == a.invoice_id).first()
        result.append({
            "approval_id": a.id,
            "invoice_id": a.invoice_id,
            "invoice_number": invoice.invoice_number if invoice else None,
            "vendor_name": invoice.vendor_name if invoice else None,
            "amount": invoice.total_amount if invoice else None,
            "currency": invoice.currency if invoice else "USD",
            "approver_email": a.approver_email,
            "approver_name": a.approver_name,
            "approval_level": a.approval_level,
            "status": a.status,
            "expires_at": str(a.expires_at) if a.expires_at else None,
            "created_at": str(a.created_at),
        })
    return result


@router.post("/{approval_id}/decide", summary="Approve or reject an invoice")
def decide_approval(
    approval_id: str,
    payload: ApprovalDecision,
    db: Session = Depends(get_db),
):
    """
    UiPath BPMN Human Task: Approver submits their decision on an invoice.
    This is the primary human-in-the-loop touchpoint for large invoices.
    """
    approval = db.query(Approval).filter(Approval.id == approval_id).first()
    if not approval:
        raise HTTPException(404, f"Approval {approval_id} not found")
    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(400, f"Approval is already in state: {approval.status}")

    # Check expiry
    if approval.expires_at:
        deadline = approval.expires_at
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > deadline:
            approval.status = ApprovalStatus.EXPIRED
            db.commit()
            raise HTTPException(410, "Approval request has expired")

    approval.status = ApprovalStatus.APPROVED if payload.approved else ApprovalStatus.REJECTED
    approval.notes = payload.notes
    approval.decided_at = datetime.now(timezone.utc)
    if payload.approver_name:
        approval.approver_name = payload.approver_name
    db.commit()

    # Update invoice status
    invoice = db.query(Invoice).filter(Invoice.id == approval.invoice_id).first()
    if invoice:
        invoice.status = InvoiceStatus.APPROVED if payload.approved else InvoiceStatus.REJECTED
        invoice.processing_notes = f"{'Approved' if payload.approved else 'Rejected'} by {approval.approver_name or approval.approver_email}: {payload.notes or ''}"
        db.commit()

    return {
        "approval_id": approval_id,
        "decision": "approved" if payload.approved else "rejected",
        "invoice_id": approval.invoice_id,
        "invoice_status": invoice.status if invoice else None,
        "decided_at": str(approval.decided_at),
    }


@router.get("/{approval_id}", summary="Get approval details")
def get_approval(approval_id: str, db: Session = Depends(get_db)):
    approval = db.query(Approval).filter(Approval.id == approval_id).first()
    if not approval:
        raise HTTPException(404, f"Approval {approval_id} not found")
    return {
        "id": approval.id,
        "invoice_id": approval.invoice_id,
        "approver_email": approval.approver_email,
        "approver_name": approval.approver_name,
        "approval_level": approval.approval_level,
        "status": approval.status,
        "notes": approval.notes,
        "created_at": str(approval.created_at),
        "decided_at": str(approval.decided_at) if approval.decided_at else None,
        "expires_at": str(approval.expires_at) if approval.expires_at else None,
    }
