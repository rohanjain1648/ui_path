"""
Real-time analytics and KPI endpoints for the AP dashboard.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.database import get_db
from backend.models import Invoice, InvoiceStatus, InvoiceException, ExceptionStatus, Approval, ApprovalStatus

router = APIRouter()


@router.get("/dashboard", summary="AP dashboard KPIs")
def dashboard_kpis(db: Session = Depends(get_db)):
    """
    Single-call endpoint for the real-time dashboard.
    Returns all KPIs needed to render the AP command center.
    """
    total_invoices = db.query(Invoice).count()
    total_amount = db.query(func.sum(Invoice.total_amount)).scalar() or 0

    status_counts = {}
    for status in InvoiceStatus:
        count = db.query(Invoice).filter(Invoice.status == status).count()
        if count > 0:
            status_counts[status.value] = count

    avg_confidence = db.query(func.avg(Invoice.extraction_confidence)).scalar() or 0
    avg_match_score = db.query(func.avg(Invoice.match_score)).filter(
        Invoice.match_score.isnot(None)
    ).scalar() or 0

    auto_approved = db.query(Invoice).filter(Invoice.status == InvoiceStatus.MATCHED).count()
    auto_approve_rate = (auto_approved / total_invoices * 100) if total_invoices > 0 else 0

    open_exceptions = db.query(InvoiceException).filter(
        InvoiceException.status == ExceptionStatus.OPEN
    ).count()
    total_exceptions = db.query(InvoiceException).count()
    exception_rate = (total_exceptions / total_invoices * 100) if total_invoices > 0 else 0

    pending_approvals = db.query(Approval).filter(
        Approval.status == ApprovalStatus.PENDING
    ).count()

    payment_scheduled = db.query(Invoice).filter(
        Invoice.status == InvoiceStatus.PAYMENT_SCHEDULED
    ).count()
    payment_amount = db.query(func.sum(Invoice.total_amount)).filter(
        Invoice.status == InvoiceStatus.PAYMENT_SCHEDULED
    ).scalar() or 0

    discounts = db.query(func.sum(Invoice.early_payment_discount)).filter(
        Invoice.early_payment_discount.isnot(None)
    ).scalar() or 0

    high_risk = db.query(Invoice).filter(Invoice.anomaly_score >= 50).count()

    return {
        "summary": {
            "total_invoices": total_invoices,
            "total_amount_usd": round(total_amount, 2),
            "auto_approve_rate_pct": round(auto_approve_rate, 1),
            "avg_extraction_confidence": round(avg_confidence, 1),
            "avg_match_score": round(avg_match_score, 1),
        },
        "pipeline": status_counts,
        "exceptions": {
            "open": open_exceptions,
            "total": total_exceptions,
            "exception_rate_pct": round(exception_rate, 1),
        },
        "approvals": {
            "pending": pending_approvals,
        },
        "payments": {
            "scheduled_count": payment_scheduled,
            "scheduled_amount_usd": round(payment_amount, 2),
            "early_payment_discounts_captured_usd": round(discounts, 2),
        },
        "risk": {
            "high_risk_invoices": high_risk,
        },
    }


@router.get("/sla", summary="SLA compliance metrics")
def sla_metrics(db: Session = Depends(get_db)):
    from backend.services.exception_engine import get_sla_status
    exceptions = db.query(InvoiceException).filter(
        InvoiceException.status != ExceptionStatus.RESOLVED
    ).all()

    breached = sum(1 for e in exceptions if get_sla_status(e) == "breached")
    at_risk = sum(1 for e in exceptions if get_sla_status(e) == "at_risk")
    on_track = sum(1 for e in exceptions if get_sla_status(e) == "on_track")

    return {
        "open_exceptions": len(exceptions),
        "sla_breached": breached,
        "sla_at_risk": at_risk,
        "sla_on_track": on_track,
        "compliance_rate_pct": round(on_track / len(exceptions) * 100, 1) if exceptions else 100.0,
    }


@router.get("/channel-breakdown", summary="Invoice volume by ingestion channel")
def channel_breakdown(db: Session = Depends(get_db)):
    rows = (
        db.query(Invoice.source_channel, func.count(Invoice.id).label("count"),
                 func.sum(Invoice.total_amount).label("total_amount"))
        .group_by(Invoice.source_channel)
        .all()
    )
    return [
        {"channel": r.source_channel or "unknown", "count": r.count, "total_amount": round(r.total_amount or 0, 2)}
        for r in rows
    ]
