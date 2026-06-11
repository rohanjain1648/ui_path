from sqlalchemy import Column, String, Float, DateTime, JSON, Enum, Text, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum
import uuid

from backend.database import Base


def new_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InvoiceStatus(str, enum.Enum):
    RECEIVED = "received"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    MATCHING = "matching"
    MATCHED = "matched"
    EXCEPTION = "exception"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    POSTED_ERP = "posted_erp"
    PAYMENT_SCHEDULED = "payment_scheduled"
    PAID = "paid"


class ExceptionType(str, enum.Enum):
    PO_NOT_FOUND = "po_not_found"
    AMOUNT_MISMATCH = "amount_mismatch"
    LINE_ITEM_MISMATCH = "line_item_mismatch"
    DUPLICATE_INVOICE = "duplicate_invoice"
    VENDOR_MISMATCH = "vendor_mismatch"
    MISSING_DATA = "missing_data"
    LOW_CONFIDENCE = "low_confidence"
    FRAUD_FLAG = "fraud_flag"
    REQUIRES_APPROVAL = "requires_approval"


class ExceptionStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


# ── ORM Models ──────────────────────────────────────────────────────────────

class Vendor(Base):
    __tablename__ = "vendors"

    id = Column(String, primary_key=True, default=new_uuid)
    name = Column(String, nullable=False, index=True)
    code = Column(String, unique=True, nullable=False)
    tax_id = Column(String)
    payment_terms = Column(String, default="net30")
    bank_account = Column(String)
    bank_routing = Column(String)
    contact_email = Column(String)
    risk_score = Column(Float, default=0.0)
    created_at = Column(DateTime, default=utcnow)
    is_active = Column(Boolean, default=True)

    invoices = relationship("Invoice", back_populates="vendor_rel")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id = Column(String, primary_key=True, default=new_uuid)
    po_number = Column(String, unique=True, nullable=False, index=True)
    vendor_id = Column(String, ForeignKey("vendors.id"))
    total_amount = Column(Float, nullable=False)
    currency = Column(String, default="USD")
    status = Column(String, default="open")
    line_items = Column(JSON, default=list)
    department = Column(String)
    cost_center = Column(String)
    gl_account = Column(String)
    created_at = Column(DateTime, default=utcnow)
    approved_by = Column(String)
    notes = Column(Text)

    vendor_rel = relationship("Vendor")
    goods_receipts = relationship("GoodsReceipt", back_populates="po_rel")


class GoodsReceipt(Base):
    __tablename__ = "goods_receipts"

    id = Column(String, primary_key=True, default=new_uuid)
    gr_number = Column(String, unique=True, nullable=False)
    po_id = Column(String, ForeignKey("purchase_orders.id"))
    received_date = Column(DateTime, default=utcnow)
    received_amount = Column(Float)
    line_items = Column(JSON, default=list)
    received_by = Column(String)

    po_rel = relationship("PurchaseOrder", back_populates="goods_receipts")


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(String, primary_key=True, default=new_uuid)
    vendor_id = Column(String, ForeignKey("vendors.id"), nullable=True)

    # Raw ingestion
    source_channel = Column(String, default="email")  # email|portal|edi|scan
    raw_content = Column(Text)
    file_path = Column(String)

    # AI-extracted fields
    vendor_name = Column(String)
    vendor_code = Column(String)
    invoice_number = Column(String, index=True)
    invoice_date = Column(String)
    due_date = Column(String)
    total_amount = Column(Float)
    tax_amount = Column(Float)
    currency = Column(String, default="USD")
    payment_terms = Column(String)
    po_reference = Column(String, index=True)
    line_items = Column(JSON, default=list)
    bank_details = Column(JSON, default=dict)
    extraction_confidence = Column(Float)
    extracted_data_raw = Column(JSON)

    # Matching results
    matched_po_id = Column(String, ForeignKey("purchase_orders.id"), nullable=True)
    match_score = Column(Float)
    match_details = Column(JSON, default=dict)

    # Anomaly / risk
    anomaly_score = Column(Float, default=0.0)
    anomaly_flags = Column(JSON, default=list)

    # Workflow
    status = Column(Enum(InvoiceStatus), default=InvoiceStatus.RECEIVED)
    erp_document_id = Column(String)
    payment_due_date = Column(String)
    early_payment_discount = Column(Float)
    payment_scheduled_date = Column(String)

    # Audit
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    processed_at = Column(DateTime)
    processing_notes = Column(Text)

    vendor_rel = relationship("Vendor", back_populates="invoices")
    exceptions = relationship("InvoiceException", back_populates="invoice_rel")
    approvals = relationship("Approval", back_populates="invoice_rel")


class InvoiceException(Base):
    __tablename__ = "invoice_exceptions"

    id = Column(String, primary_key=True, default=new_uuid)
    invoice_id = Column(String, ForeignKey("invoices.id"), nullable=False)
    exception_type = Column(Enum(ExceptionType), nullable=False)
    description = Column(Text, nullable=False)
    ai_recommendation = Column(Text)
    assigned_to = Column(String)
    status = Column(Enum(ExceptionStatus), default=ExceptionStatus.OPEN)
    resolution_notes = Column(Text)
    created_at = Column(DateTime, default=utcnow)
    resolved_at = Column(DateTime)
    sla_deadline = Column(DateTime)

    invoice_rel = relationship("Invoice", back_populates="exceptions")


class Approval(Base):
    __tablename__ = "approvals"

    id = Column(String, primary_key=True, default=new_uuid)
    invoice_id = Column(String, ForeignKey("invoices.id"), nullable=False)
    approver_email = Column(String, nullable=False)
    approver_name = Column(String)
    approval_level = Column(String)  # manager|director|cfo
    status = Column(Enum(ApprovalStatus), default=ApprovalStatus.PENDING)
    notes = Column(Text)
    created_at = Column(DateTime, default=utcnow)
    decided_at = Column(DateTime)
    expires_at = Column(DateTime)

    invoice_rel = relationship("Invoice", back_populates="approvals")
