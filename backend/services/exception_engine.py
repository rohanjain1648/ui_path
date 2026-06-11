"""
Exception classification, routing, and SLA management for AP exceptions.
Determines who gets assigned an exception based on type, amount, and company rules.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.orm import Session

from backend.models import Invoice, InvoiceException, ExceptionType, ExceptionStatus, Approval, ApprovalStatus
from backend.config import get_settings

settings = get_settings()


# SLA hours by exception type
_SLA_HOURS: dict[str, int] = {
    ExceptionType.FRAUD_FLAG: 4,
    ExceptionType.DUPLICATE_INVOICE: 8,
    ExceptionType.PO_NOT_FOUND: 24,
    ExceptionType.AMOUNT_MISMATCH: 24,
    ExceptionType.VENDOR_MISMATCH: 24,
    ExceptionType.LINE_ITEM_MISMATCH: 48,
    ExceptionType.MISSING_DATA: 48,
    ExceptionType.LOW_CONFIDENCE: 72,
    ExceptionType.REQUIRES_APPROVAL: 48,
}

# Routing rules: exception_type → assignee_role
_ROUTING: dict[str, str] = {
    ExceptionType.FRAUD_FLAG: "ap_manager@company.com",
    ExceptionType.DUPLICATE_INVOICE: "ap_team@company.com",
    ExceptionType.PO_NOT_FOUND: "procurement@company.com",
    ExceptionType.AMOUNT_MISMATCH: "ap_team@company.com",
    ExceptionType.VENDOR_MISMATCH: "vendor_management@company.com",
    ExceptionType.LINE_ITEM_MISMATCH: "ap_team@company.com",
    ExceptionType.MISSING_DATA: "ap_team@company.com",
    ExceptionType.LOW_CONFIDENCE: "ap_team@company.com",
    ExceptionType.REQUIRES_APPROVAL: "approvals@company.com",
}


def create_exceptions(
    invoice: Invoice,
    discrepancies: list[str],
    anomaly_flags: list[dict],
    match_score: float,
    extraction_confidence: float,
    db: Session,
    ai_recommendations: Optional[dict] = None,
) -> list[InvoiceException]:
    """
    Given matching/extraction results, create InvoiceException records.
    Returns list of created exceptions.
    """
    now = datetime.now(timezone.utc)
    exceptions = []

    # Fraud flags first (highest priority)
    for flag in (anomaly_flags or []):
        if flag.get("severity") in ("high", "critical"):
            exc = _make_exception(
                invoice=invoice,
                exc_type=ExceptionType.FRAUD_FLAG,
                description=f"Anomaly detected: {flag.get('description', '')}",
                ai_rec=f"Evidence: {flag.get('evidence', '')}. Severity: {flag.get('severity', '')}.",
                now=now,
                db=db,
            )
            exceptions.append(exc)

    # Duplicate detection
    if any("duplicate" in d.lower() for d in discrepancies):
        exc = _make_exception(invoice, ExceptionType.DUPLICATE_INVOICE,
                              "Possible duplicate invoice detected", None, now, db)
        exceptions.append(exc)

    # PO not found
    if any("not found" in d.lower() for d in discrepancies):
        exc = _make_exception(invoice, ExceptionType.PO_NOT_FOUND,
                              f"PO reference '{invoice.po_reference}' not found in system",
                              "Contact procurement to verify if PO exists or request new PO creation.",
                              now, db)
        exceptions.append(exc)

    # Amount mismatch
    if any("amount mismatch" in d.lower() for d in discrepancies):
        mismatch = next((d for d in discrepancies if "amount mismatch" in d.lower()), "")
        exc = _make_exception(invoice, ExceptionType.AMOUNT_MISMATCH,
                              mismatch or "Invoice amount differs from PO",
                              "Obtain credit note from vendor or request PO amendment.",
                              now, db)
        exceptions.append(exc)

    # Vendor mismatch
    if any("vendor mismatch" in d.lower() for d in discrepancies):
        exc = _make_exception(invoice, ExceptionType.VENDOR_MISMATCH,
                              "Invoice vendor does not match PO vendor",
                              "Verify with procurement whether vendor substitution was approved.",
                              now, db)
        exceptions.append(exc)

    # Line item mismatch
    line_issues = [d for d in discrepancies if "line" in d.lower() and "mismatch" in d.lower()]
    if line_issues:
        exc = _make_exception(invoice, ExceptionType.LINE_ITEM_MISMATCH,
                              f"{len(line_issues)} line item discrepancies found",
                              "Request revised invoice or PO amendment for mismatched lines.",
                              now, db)
        exceptions.append(exc)

    # Low extraction confidence
    if extraction_confidence < 70:
        exc = _make_exception(invoice, ExceptionType.LOW_CONFIDENCE,
                              f"AI extraction confidence {extraction_confidence:.0f}% — below 70% threshold",
                              "Manually verify all extracted fields against original invoice.",
                              now, db)
        exceptions.append(exc)

    # Requires approval (large amount, no exception but above threshold)
    if not exceptions and invoice.total_amount and invoice.total_amount > settings.auto_approve_threshold:
        exc = _make_exception(invoice, ExceptionType.REQUIRES_APPROVAL,
                              f"Invoice amount ${invoice.total_amount:,.2f} requires human approval",
                              None, now, db)
        exceptions.append(exc)

    return exceptions


def _make_exception(
    invoice: Invoice,
    exc_type: ExceptionType,
    description: str,
    ai_rec: Optional[str],
    now: datetime,
    db: Session,
) -> InvoiceException:
    sla_hours = _SLA_HOURS.get(exc_type, 48)
    assignee = _ROUTING.get(exc_type, "ap_team@company.com")

    exc = InvoiceException(
        invoice_id=invoice.id,
        exception_type=exc_type,
        description=description,
        ai_recommendation=ai_rec,
        assigned_to=assignee,
        status=ExceptionStatus.OPEN,
        sla_deadline=now + timedelta(hours=sla_hours),
    )
    db.add(exc)
    return exc


def create_approval_request(invoice: Invoice, db: Session) -> Approval:
    """Route invoice to the correct approval level based on amount."""
    amount = invoice.total_amount or 0

    if amount <= settings.manager_approval_threshold:
        level = "manager"
        approver = "manager@company.com"
        approver_name = "Department Manager"
    elif amount <= settings.cfo_approval_threshold:
        level = "director"
        approver = "director@company.com"
        approver_name = "Finance Director"
    else:
        level = "cfo"
        approver = "cfo@company.com"
        approver_name = "CFO"

    approval = Approval(
        invoice_id=invoice.id,
        approver_email=approver,
        approver_name=approver_name,
        approval_level=level,
        status=ApprovalStatus.PENDING,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=48),
    )
    db.add(approval)
    return approval


def get_sla_status(exception: InvoiceException) -> str:
    """Return 'on_track', 'at_risk', or 'breached'."""
    if not exception.sla_deadline:
        return "unknown"
    now = datetime.now(timezone.utc)
    deadline = exception.sla_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    remaining = (deadline - now).total_seconds() / 3600
    if remaining < 0:
        return "breached"
    if remaining < 4:
        return "at_risk"
    return "on_track"
