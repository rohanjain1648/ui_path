"""
Invoice ingestion, AI processing, and workflow orchestration endpoints.
These are the primary service task targets called by UiPath Maestro BPMN.
"""
import base64
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Invoice, InvoiceStatus, Vendor
from backend.services import ai_service, matching_engine, exception_engine, erp_mock

router = APIRouter()


# ── Request/Response schemas ─────────────────────────────────────────────────

class InvoiceTextPayload(BaseModel):
    text: str
    source_channel: str = "portal"
    vendor_code: Optional[str] = None


class InvoiceResponse(BaseModel):
    id: str
    status: str
    vendor_name: Optional[str]
    invoice_number: Optional[str]
    invoice_date: Optional[str]
    total_amount: Optional[float]
    currency: str
    po_reference: Optional[str]
    extraction_confidence: Optional[float]
    anomaly_score: Optional[float]
    match_score: Optional[float]
    created_at: str

    class Config:
        from_attributes = True


class ProcessingResult(BaseModel):
    invoice_id: str
    status: str
    match_result: Optional[dict]
    exceptions_created: int
    erp_posting: Optional[dict]
    payment_scheduling: Optional[dict]
    message: str


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/ingest/text", response_model=InvoiceResponse, summary="Ingest invoice from raw text")
async def ingest_invoice_text(
    payload: InvoiceTextPayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    UiPath BPMN Task 1: Receive invoice from email/portal as text.
    Creates invoice record and triggers AI extraction in background.
    """
    invoice = Invoice(
        source_channel=payload.source_channel,
        raw_content=payload.text,
        status=InvoiceStatus.EXTRACTING,
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)

    background_tasks.add_task(_run_full_pipeline, invoice.id)
    return _to_response(invoice)


@router.post("/ingest/file", response_model=InvoiceResponse, summary="Ingest invoice from uploaded file")
async def ingest_invoice_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    source_channel: str = Form(default="scan"),
    db: Session = Depends(get_db),
):
    """
    UiPath BPMN Task 1 (alt): Receive invoice as uploaded file (PDF/image).
    Converts to base64 for Claude vision extraction.
    """
    content = await file.read()
    b64 = base64.b64encode(content).decode("utf-8")
    media_type = file.content_type or "image/jpeg"

    invoice = Invoice(
        source_channel=source_channel,
        raw_content=f"[binary:{file.filename}]",
        file_path=file.filename,
        status=InvoiceStatus.EXTRACTING,
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)

    background_tasks.add_task(_run_full_pipeline, invoice.id, b64, media_type)
    return _to_response(invoice)


@router.post("/{invoice_id}/extract", summary="(Re)run AI extraction on an invoice")
async def extract_invoice(invoice_id: str, db: Session = Depends(get_db)):
    """
    UiPath BPMN Task 2: Trigger/retry Claude extraction for a specific invoice.
    Useful for manual re-extraction after data corrections.
    """
    invoice = _get_or_404(invoice_id, db)
    extracted = await ai_service.extract_invoice(invoice.raw_content or "")
    _apply_extraction(invoice, extracted)
    invoice.status = InvoiceStatus.EXTRACTED
    db.commit()
    db.refresh(invoice)
    return {"invoice_id": invoice_id, "extraction": extracted, "status": invoice.status}


@router.post("/{invoice_id}/match", summary="Run 3-way PO match on an invoice")
async def match_invoice(invoice_id: str, db: Session = Depends(get_db)):
    """
    UiPath BPMN Task 3: Attempt to match invoice to PO and goods receipt.
    Returns match score, discrepancies, and routing recommendation.
    """
    invoice = _get_or_404(invoice_id, db)
    if invoice.status not in (InvoiceStatus.EXTRACTED, InvoiceStatus.MATCHING):
        raise HTTPException(400, "Invoice must be in EXTRACTED state before matching")

    invoice.status = InvoiceStatus.MATCHING
    db.commit()

    result = matching_engine.match_invoice_to_po(invoice, db)

    invoice.match_score = result.match_score
    invoice.match_details = {
        "discrepancies": result.discrepancies,
        "within_tolerance": result.within_tolerance,
        "auto_approvable": result.auto_approvable,
        **result.details,
    }

    if result.po:
        po_obj = db.query(__import__("backend.models", fromlist=["PurchaseOrder"]).PurchaseOrder).filter_by(
            po_number=invoice.po_reference
        ).first()
        if po_obj:
            invoice.matched_po_id = po_obj.id

    if result.matched and result.auto_approvable:
        invoice.status = InvoiceStatus.MATCHED
    elif result.matched and not result.auto_approvable:
        invoice.status = InvoiceStatus.PENDING_APPROVAL
    else:
        invoice.status = InvoiceStatus.EXCEPTION

    db.commit()
    db.refresh(invoice)

    return {
        "invoice_id": invoice_id,
        "status": invoice.status,
        "match_score": result.match_score,
        "matched": result.matched,
        "within_tolerance": result.within_tolerance,
        "auto_approvable": result.auto_approvable,
        "discrepancies": result.discrepancies,
        "po": result.po,
        "gr": result.gr,
    }


@router.post("/{invoice_id}/post-erp", summary="Post approved invoice to ERP")
async def post_to_erp(invoice_id: str, db: Session = Depends(get_db)):
    """
    UiPath BPMN Task 6: Post approved invoice to ERP and schedule payment.
    """
    invoice = _get_or_404(invoice_id, db)
    if invoice.status not in (InvoiceStatus.APPROVED, InvoiceStatus.MATCHED):
        raise HTTPException(400, f"Invoice status is {invoice.status} — must be APPROVED or MATCHED")

    erp_result = erp_mock.post_to_erp(invoice)
    invoice.erp_document_id = erp_result["erp_document_id"]
    invoice.status = InvoiceStatus.POSTED_ERP
    db.commit()

    # Optimize payment timing
    pay_optimization = await ai_service.optimize_payment_timing(
        {
            "vendor_name": invoice.vendor_name,
            "total_amount": invoice.total_amount,
            "currency": invoice.currency,
            "payment_terms": invoice.payment_terms,
            "due_date": invoice.due_date,
            "invoice_date": invoice.invoice_date,
        }
    )

    early = pay_optimization.get("discount_amount", 0) > 0
    payment = erp_mock.schedule_payment(invoice, early_payment=early)

    invoice.payment_scheduled_date = payment["payment_date"]
    invoice.early_payment_discount = payment.get("discount_taken", 0)
    invoice.status = InvoiceStatus.PAYMENT_SCHEDULED
    db.commit()
    db.refresh(invoice)

    return {
        "invoice_id": invoice_id,
        "erp_posting": erp_result,
        "payment_optimization": pay_optimization,
        "payment_scheduling": payment,
        "status": invoice.status,
    }


@router.get("/{invoice_id}", response_model=dict, summary="Get invoice details")
def get_invoice(invoice_id: str, db: Session = Depends(get_db)):
    invoice = _get_or_404(invoice_id, db)
    return {
        "id": invoice.id,
        "status": invoice.status,
        "vendor_name": invoice.vendor_name,
        "vendor_code": invoice.vendor_code,
        "invoice_number": invoice.invoice_number,
        "invoice_date": invoice.invoice_date,
        "due_date": invoice.due_date,
        "total_amount": invoice.total_amount,
        "currency": invoice.currency,
        "payment_terms": invoice.payment_terms,
        "po_reference": invoice.po_reference,
        "line_items": invoice.line_items,
        "extraction_confidence": invoice.extraction_confidence,
        "anomaly_score": invoice.anomaly_score,
        "anomaly_flags": invoice.anomaly_flags,
        "match_score": invoice.match_score,
        "match_details": invoice.match_details,
        "erp_document_id": invoice.erp_document_id,
        "payment_scheduled_date": invoice.payment_scheduled_date,
        "early_payment_discount": invoice.early_payment_discount,
        "source_channel": invoice.source_channel,
        "created_at": str(invoice.created_at),
        "updated_at": str(invoice.updated_at),
    }


@router.get("/", summary="List all invoices")
def list_invoices(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(Invoice)
    if status:
        q = q.filter(Invoice.status == status)
    total = q.count()
    invoices = q.order_by(Invoice.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "invoices": [_to_response(inv).__dict__ for inv in invoices],
    }


# ── Internal helpers ─────────────────────────────────────────────────────────

def _get_or_404(invoice_id: str, db: Session) -> Invoice:
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(404, f"Invoice {invoice_id} not found")
    return inv


def _to_response(inv: Invoice) -> InvoiceResponse:
    return InvoiceResponse(
        id=inv.id,
        status=inv.status,
        vendor_name=inv.vendor_name,
        invoice_number=inv.invoice_number,
        invoice_date=inv.invoice_date,
        total_amount=inv.total_amount,
        currency=inv.currency or "USD",
        po_reference=inv.po_reference,
        extraction_confidence=inv.extraction_confidence,
        anomaly_score=inv.anomaly_score,
        match_score=inv.match_score,
        created_at=str(inv.created_at),
    )


def _apply_extraction(invoice: Invoice, data: dict) -> None:
    invoice.vendor_name = data.get("vendor_name")
    invoice.vendor_code = data.get("vendor_code")
    invoice.invoice_number = data.get("invoice_number")
    invoice.invoice_date = data.get("invoice_date")
    invoice.due_date = data.get("due_date")
    invoice.total_amount = data.get("total_amount")
    invoice.tax_amount = data.get("tax_amount", 0)
    invoice.currency = data.get("currency", "USD")
    invoice.payment_terms = data.get("payment_terms")
    invoice.po_reference = data.get("po_reference")
    invoice.line_items = data.get("line_items", [])
    invoice.bank_details = data.get("bank_details", {})
    invoice.extraction_confidence = data.get("confidence_score", 0)
    invoice.extracted_data_raw = data
    invoice.updated_at = datetime.now(timezone.utc)


async def _run_full_pipeline(
    invoice_id: str,
    image_b64: Optional[str] = None,
    media_type: str = "image/jpeg",
):
    """
    Full asynchronous processing pipeline.
    Called as a background task after invoice ingestion.
    Mirrors the UiPath Maestro BPMN process flow in code.
    """
    from backend.database import SessionLocal
    db = SessionLocal()
    try:
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not invoice:
            return

        # Step 1: Extract
        extracted = await ai_service.extract_invoice(
            invoice.raw_content or "", image_b64, media_type
        )
        _apply_extraction(invoice, extracted)
        invoice.status = InvoiceStatus.EXTRACTED
        db.commit()

        # Resolve vendor
        if invoice.vendor_name:
            vendor = db.query(Vendor).filter(
                Vendor.name.ilike(f"%{invoice.vendor_name}%")
            ).first()
            if vendor:
                invoice.vendor_id = vendor.id

        # Step 2: Anomaly detection
        anomaly = await ai_service.detect_anomalies(
            invoice_data=extracted,
            vendor_master={"name": invoice.vendor_name, "bank_account": None},
        )
        invoice.anomaly_score = anomaly.get("anomaly_score", 0)
        invoice.anomaly_flags = anomaly.get("flags", [])
        db.commit()

        # Step 3: Duplicate check
        dup_check = erp_mock.check_duplicate_in_erp(
            invoice.vendor_id or "", invoice.invoice_number or "", invoice.total_amount or 0
        )

        # Step 4: 3-way match
        invoice.status = InvoiceStatus.MATCHING
        db.commit()
        match_result = matching_engine.match_invoice_to_po(invoice, db)
        invoice.match_score = match_result.match_score
        invoice.match_details = {
            "discrepancies": match_result.discrepancies,
            "within_tolerance": match_result.within_tolerance,
            "auto_approvable": match_result.auto_approvable,
            **match_result.details,
        }
        db.commit()

        # Step 5: Exception creation
        all_discrepancies = match_result.discrepancies
        if dup_check.get("is_duplicate"):
            all_discrepancies.append("Duplicate invoice detected in ERP")

        exceptions = exception_engine.create_exceptions(
            invoice=invoice,
            discrepancies=all_discrepancies,
            anomaly_flags=invoice.anomaly_flags or [],
            match_score=match_result.match_score,
            extraction_confidence=invoice.extraction_confidence or 0,
            db=db,
        )
        db.commit()

        # Step 6: Route
        if exceptions:
            invoice.status = InvoiceStatus.EXCEPTION
        elif match_result.auto_approvable:
            invoice.status = InvoiceStatus.MATCHED
        else:
            invoice.status = InvoiceStatus.PENDING_APPROVAL
            exception_engine.create_approval_request(invoice, db)

        invoice.processed_at = datetime.now(timezone.utc)
        db.commit()

    finally:
        db.close()
