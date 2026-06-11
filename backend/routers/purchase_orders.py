from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import PurchaseOrder, Vendor, GoodsReceipt

router = APIRouter()


class POCreate(BaseModel):
    po_number: str
    vendor_code: str
    total_amount: float
    currency: str = "USD"
    department: Optional[str] = None
    cost_center: Optional[str] = None
    gl_account: Optional[str] = None
    line_items: List[dict] = []
    approved_by: Optional[str] = None
    notes: Optional[str] = None


class GRCreate(BaseModel):
    po_number: str
    gr_number: str
    received_amount: float
    received_by: str
    line_items: List[dict] = []


@router.post("/", summary="Create a purchase order")
def create_po(payload: POCreate, db: Session = Depends(get_db)):
    vendor = db.query(Vendor).filter(Vendor.code == payload.vendor_code).first()
    if not vendor:
        raise HTTPException(404, f"Vendor with code '{payload.vendor_code}' not found")

    existing = db.query(PurchaseOrder).filter(PurchaseOrder.po_number == payload.po_number).first()
    if existing:
        raise HTTPException(409, f"PO {payload.po_number} already exists")

    po = PurchaseOrder(
        po_number=payload.po_number,
        vendor_id=vendor.id,
        total_amount=payload.total_amount,
        currency=payload.currency,
        department=payload.department,
        cost_center=payload.cost_center,
        gl_account=payload.gl_account,
        line_items=payload.line_items,
        approved_by=payload.approved_by,
        notes=payload.notes,
        status="open",
    )
    db.add(po)
    db.commit()
    db.refresh(po)
    return {"id": po.id, "po_number": po.po_number, "status": "created"}


@router.post("/goods-receipt", summary="Record a goods receipt against a PO")
def create_goods_receipt(payload: GRCreate, db: Session = Depends(get_db)):
    po = db.query(PurchaseOrder).filter(PurchaseOrder.po_number == payload.po_number).first()
    if not po:
        raise HTTPException(404, f"PO {payload.po_number} not found")

    gr = GoodsReceipt(
        gr_number=payload.gr_number,
        po_id=po.id,
        received_amount=payload.received_amount,
        received_by=payload.received_by,
        line_items=payload.line_items,
    )
    db.add(gr)
    db.commit()
    db.refresh(gr)
    return {"id": gr.id, "gr_number": gr.gr_number, "po_number": payload.po_number, "status": "recorded"}


@router.get("/{po_number}", summary="Get PO by number")
def get_po(po_number: str, db: Session = Depends(get_db)):
    po = db.query(PurchaseOrder).filter(PurchaseOrder.po_number == po_number).first()
    if not po:
        raise HTTPException(404, f"PO {po_number} not found")
    return {
        "id": po.id,
        "po_number": po.po_number,
        "vendor_id": po.vendor_id,
        "total_amount": po.total_amount,
        "currency": po.currency,
        "status": po.status,
        "department": po.department,
        "cost_center": po.cost_center,
        "gl_account": po.gl_account,
        "line_items": po.line_items,
        "approved_by": po.approved_by,
        "created_at": str(po.created_at),
    }


@router.get("/", summary="List purchase orders")
def list_pos(
    vendor_code: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    q = db.query(PurchaseOrder)
    if vendor_code:
        vendor = db.query(Vendor).filter(Vendor.code == vendor_code).first()
        if vendor:
            q = q.filter(PurchaseOrder.vendor_id == vendor.id)
    if status:
        q = q.filter(PurchaseOrder.status == status)
    pos = q.order_by(PurchaseOrder.created_at.desc()).limit(limit).all()
    return [{"id": p.id, "po_number": p.po_number, "total_amount": p.total_amount,
             "status": p.status, "created_at": str(p.created_at)} for p in pos]
