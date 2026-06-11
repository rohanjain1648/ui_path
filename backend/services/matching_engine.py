"""
Three-way matching engine: Invoice ↔ Purchase Order ↔ Goods Receipt.
Handles tolerance-based matching, line-item reconciliation, and match scoring.
"""
from dataclasses import dataclass, field
from typing import Optional
from sqlalchemy.orm import Session

from backend.models import Invoice, PurchaseOrder, GoodsReceipt, InvoiceStatus
from backend.config import get_settings

settings = get_settings()


@dataclass
class MatchResult:
    matched: bool
    match_score: float          # 0-100
    po: Optional[dict]
    gr: Optional[dict]
    discrepancies: list = field(default_factory=list)
    within_tolerance: bool = False
    auto_approvable: bool = False
    details: dict = field(default_factory=dict)


def _pct_diff(a: float, b: float) -> float:
    if b == 0:
        return 100.0
    return abs(a - b) / b * 100


def match_invoice_to_po(invoice: Invoice, db: Session) -> MatchResult:
    """
    Attempt to match an invoice to a PO and goods receipt.
    Returns a MatchResult with full reconciliation detail.
    """
    po_ref = invoice.po_reference
    if not po_ref:
        return MatchResult(
            matched=False,
            match_score=0,
            po=None,
            gr=None,
            discrepancies=["No PO reference found on invoice"],
        )

    po: Optional[PurchaseOrder] = (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.po_number == po_ref)
        .first()
    )

    if not po:
        return MatchResult(
            matched=False,
            match_score=0,
            po=None,
            gr=None,
            discrepancies=[f"PO {po_ref} not found in system"],
        )

    discrepancies = []
    score = 100.0

    # ── Amount match ──────────────────────────────────────────────────────
    inv_amount = invoice.total_amount or 0
    po_amount = po.total_amount or 0
    amount_pct = _pct_diff(inv_amount, po_amount)
    tol = settings.po_match_tolerance_percent

    if amount_pct > tol:
        discrepancies.append(
            f"Amount mismatch: invoice {inv_amount:.2f} vs PO {po_amount:.2f} "
            f"({amount_pct:.1f}% — tolerance {tol}%)"
        )
        score -= min(40, amount_pct * 4)

    # ── Vendor match ──────────────────────────────────────────────────────
    if po.vendor_id and invoice.vendor_id and po.vendor_id != invoice.vendor_id:
        discrepancies.append(
            f"Vendor mismatch: invoice vendor_id {invoice.vendor_id} vs PO vendor_id {po.vendor_id}"
        )
        score -= 30

    # ── Currency match ────────────────────────────────────────────────────
    if invoice.currency and po.currency and invoice.currency != po.currency:
        discrepancies.append(
            f"Currency mismatch: invoice {invoice.currency} vs PO {po.currency}"
        )
        score -= 10

    # ── Line item match ───────────────────────────────────────────────────
    inv_items = invoice.line_items or []
    po_items = po.line_items or []
    line_discrepancies = _match_line_items(inv_items, po_items)
    if line_discrepancies:
        discrepancies.extend(line_discrepancies)
        score -= min(20, len(line_discrepancies) * 5)

    # ── Goods receipt match ───────────────────────────────────────────────
    gr: Optional[GoodsReceipt] = (
        db.query(GoodsReceipt)
        .filter(GoodsReceipt.po_id == po.id)
        .order_by(GoodsReceipt.received_date.desc())
        .first()
    )

    if not gr:
        discrepancies.append("No goods receipt recorded for this PO — 3-way match incomplete")
        score -= 15
    else:
        gr_amount = gr.received_amount or 0
        gr_pct = _pct_diff(inv_amount, gr_amount)
        if gr_pct > tol:
            discrepancies.append(
                f"GR amount mismatch: invoice {inv_amount:.2f} vs GR {gr_amount:.2f} ({gr_pct:.1f}%)"
            )
            score -= min(20, gr_pct * 2)

    score = max(0.0, score)
    matched = len(discrepancies) == 0 or (score >= 80 and amount_pct <= tol)
    within_tolerance = amount_pct <= tol and score >= 70
    auto_approvable = (
        within_tolerance
        and score >= 85
        and (invoice.total_amount or 0) <= settings.auto_approve_threshold
        and not any(d.startswith("Vendor mismatch") for d in discrepancies)
    )

    po_dict = {
        "id": po.id,
        "po_number": po.po_number,
        "total_amount": po.total_amount,
        "currency": po.currency,
        "vendor_id": po.vendor_id,
        "department": po.department,
        "cost_center": po.cost_center,
        "gl_account": po.gl_account,
        "line_items": po.line_items,
    }

    gr_dict = {
        "id": gr.id,
        "gr_number": gr.gr_number,
        "received_amount": gr.received_amount,
        "received_date": str(gr.received_date),
    } if gr else None

    return MatchResult(
        matched=matched,
        match_score=round(score, 1),
        po=po_dict,
        gr=gr_dict,
        discrepancies=discrepancies,
        within_tolerance=within_tolerance,
        auto_approvable=auto_approvable,
        details={
            "amount_pct_diff": round(amount_pct, 2),
            "line_items_checked": len(inv_items),
            "gr_found": gr is not None,
            "tolerance_pct": tol,
        },
    )


def _match_line_items(inv_items: list, po_items: list) -> list:
    """Compare invoice line items against PO line items; return discrepancy strings."""
    issues = []
    if not po_items:
        return issues

    tol = settings.line_item_tolerance_percent

    for inv_item in inv_items:
        inv_desc = (inv_item.get("description") or "").lower()
        inv_total = inv_item.get("total_price", 0) or 0

        best_match = None
        best_score = 0

        for po_item in po_items:
            po_desc = (po_item.get("description") or "").lower()
            overlap = len(set(inv_desc.split()) & set(po_desc.split()))
            score = overlap / max(len(po_desc.split()), 1)
            if score > best_score:
                best_score = score
                best_match = po_item

        if best_match is None or best_score < 0.3:
            issues.append(f"Unmatched line item: '{inv_item.get('description', 'Unknown')}'")
            continue

        po_total = best_match.get("total_price", 0) or 0
        if po_total > 0:
            pct = _pct_diff(inv_total, po_total)
            if pct > tol:
                issues.append(
                    f"Line '{inv_item.get('description', '')[:40]}': "
                    f"invoice {inv_total:.2f} vs PO {po_total:.2f} ({pct:.1f}%)"
                )

    return issues
