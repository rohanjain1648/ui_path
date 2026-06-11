"""
Mock ERP integration layer. In production this would call SAP, Oracle, or NetSuite APIs.
Simulates GL posting, vendor payment scheduling, and document creation.
"""
import uuid
import random
from datetime import datetime, timezone, timedelta
from typing import Optional

from backend.models import Invoice
from backend.config import get_settings

settings = get_settings()


def post_to_erp(invoice: Invoice, gl_account: Optional[str] = None) -> dict:
    """
    Post approved invoice to ERP (mock).
    Returns ERP document number and posting confirmation.
    """
    # Derive GL account from PO or vendor category if not provided
    gl = gl_account or _infer_gl_account(invoice)

    erp_doc = f"FI-{datetime.now().strftime('%Y%m')}-{random.randint(10000, 99999)}"

    return {
        "erp_document_id": erp_doc,
        "gl_account": gl,
        "cost_center": _infer_cost_center(invoice),
        "posting_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "fiscal_period": _get_fiscal_period(),
        "status": "posted",
        "erp_system": "SAP S/4HANA (mock)",
        "journal_entry": {
            "debit": {"account": gl, "amount": invoice.total_amount, "currency": invoice.currency},
            "credit": {"account": "21000-AP-Payable", "amount": invoice.total_amount, "currency": invoice.currency},
        },
    }


def schedule_payment(
    invoice: Invoice,
    early_payment: bool = False,
    override_date: Optional[str] = None,
) -> dict:
    """
    Schedule payment in mock payment system.
    Applies early payment discount logic for 2/10 net 30 terms.
    """
    terms = invoice.payment_terms or "net30"
    due = _parse_due_date(terms, invoice.invoice_date)

    discount_amount = 0.0
    payment_date = override_date or due

    if early_payment and "2/10" in terms:
        # 2% discount if paid within 10 days
        discount_amount = round((invoice.total_amount or 0) * 0.02, 2)
        from datetime import datetime as dt
        try:
            inv_date = dt.strptime(invoice.invoice_date or "", "%Y-%m-%d")
            payment_date = (inv_date + timedelta(days=9)).strftime("%Y-%m-%d")
        except ValueError:
            pass

    net_payment = round((invoice.total_amount or 0) - discount_amount, 2)
    payment_ref = f"PAY-{uuid.uuid4().hex[:10].upper()}"

    return {
        "payment_reference": payment_ref,
        "vendor_id": invoice.vendor_id,
        "invoice_id": invoice.id,
        "gross_amount": invoice.total_amount,
        "discount_taken": discount_amount,
        "net_payment_amount": net_payment,
        "payment_date": payment_date,
        "payment_method": "ACH",
        "bank_account": invoice.bank_details.get("account_number") if invoice.bank_details else None,
        "status": "scheduled",
    }


def check_duplicate_in_erp(vendor_id: str, invoice_number: str, amount: float) -> dict:
    """Check ERP for duplicate invoice. Mock returns random result."""
    is_duplicate = False
    existing_doc = None

    # Simulate ~5% duplicate rate for demo
    if random.random() < 0.05:
        is_duplicate = True
        existing_doc = f"FI-{datetime.now().strftime('%Y%m')}-{random.randint(10000, 99999)}"

    return {
        "is_duplicate": is_duplicate,
        "existing_erp_document": existing_doc,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _infer_gl_account(invoice: Invoice) -> str:
    name = (invoice.vendor_name or "").lower()
    if any(k in name for k in ("software", "saas", "cloud", "tech")):
        return "64000-Software-Licenses"
    if any(k in name for k in ("office", "supply", "stationery")):
        return "62000-Office-Supplies"
    if any(k in name for k in ("consult", "service", "professional")):
        return "65000-Professional-Services"
    if any(k in name for k in ("travel", "hotel", "airline", "flight")):
        return "63000-Travel-Entertainment"
    return "69000-General-Operating-Expense"


def _infer_cost_center(invoice: Invoice) -> str:
    return "CC-1000-Finance"


def _get_fiscal_period() -> str:
    now = datetime.now()
    return f"FY{now.year}-P{now.month:02d}"


def _parse_due_date(terms: str, invoice_date: Optional[str]) -> str:
    try:
        from datetime import datetime as dt
        base = dt.strptime(invoice_date or "", "%Y-%m-%d") if invoice_date else datetime.now()
    except ValueError:
        base = datetime.now()

    if "net60" in terms or "net 60" in terms:
        days = 60
    elif "net45" in terms or "net 45" in terms:
        days = 45
    elif "net30" in terms or "net 30" in terms or "2/10" in terms:
        days = 30
    elif "net15" in terms or "net 15" in terms:
        days = 15
    elif "due on receipt" in terms or "cod" in terms:
        days = 0
    else:
        days = 30

    return (base + timedelta(days=days)).strftime("%Y-%m-%d")
