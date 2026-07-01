"""
IntelliFlow AP — AI-Native Accounts Payable Orchestration
FastAPI application — REST API consumed by UiPath Maestro BPMN service tasks.
"""
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import pathlib

from backend.database import engine, Base, SessionLocal
from backend.routers import invoices, purchase_orders, exceptions_router, approvals, analytics, webhooks


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _seed_demo_data()
    yield


app = FastAPI(
    title="IntelliFlow AP",
    description=(
        "AI-native Accounts Payable orchestration platform. "
        "Backend API consumed by UiPath Maestro BPMN service tasks. "
        "Powered by Groq LLaMA-3.3-70B for document intelligence."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(invoices.router, prefix="/api/invoices", tags=["Invoices"])
app.include_router(purchase_orders.router, prefix="/api/purchase-orders", tags=["Purchase Orders"])
app.include_router(exceptions_router.router, prefix="/api/exceptions", tags=["Exceptions"])
app.include_router(approvals.router, prefix="/api/approvals", tags=["Approvals"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["Analytics"])
app.include_router(webhooks.router, prefix="/api/webhooks", tags=["Webhooks"])


# Serve frontend SPA
frontend_path = pathlib.Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_spa():
        return FileResponse(str(frontend_path / "index.html"))


@app.get("/api/health", tags=["Health"])
def health():
    return {"status": "healthy", "service": "IntelliFlow AP", "version": "1.0.0"}


# ── Demo data seeder ─────────────────────────────────────────────────────────

def _seed_demo_data():
    """Seed initial vendors, POs, and GRs so demos work out of the box."""
    from backend.models import Vendor, PurchaseOrder, GoodsReceipt
    db = SessionLocal()
    try:
        if db.query(Vendor).count() > 0:
            return  # already seeded

        sample_path = pathlib.Path(__file__).parent.parent / "sample_data"

        # Load vendors
        vendors_file = sample_path / "vendors.json"
        if vendors_file.exists():
            vendors_data = json.loads(vendors_file.read_text())
            vendor_map = {}
            for v in vendors_data:
                vendor = Vendor(**v)
                db.add(vendor)
                vendor_map[v["code"]] = vendor
            db.flush()

        # Load POs
        pos_file = sample_path / "purchase_orders.json"
        if pos_file.exists():
            pos_data = json.loads(pos_file.read_text())
            po_map = {}
            for p in pos_data:
                vendor = db.query(Vendor).filter(Vendor.code == p.pop("vendor_code", None)).first()
                if vendor:
                    po = PurchaseOrder(vendor_id=vendor.id, **p)
                    db.add(po)
                    po_map[po.po_number] = po
            db.flush()

        # Load GRs
        grs_file = sample_path / "goods_receipts.json"
        if grs_file.exists():
            grs_data = json.loads(grs_file.read_text())
            for g in grs_data:
                po_number = g.pop("po_number", None)
                po = db.query(PurchaseOrder).filter(PurchaseOrder.po_number == po_number).first()
                if po:
                    gr = GoodsReceipt(po_id=po.id, **g)
                    db.add(gr)

        db.commit()
        print("Demo data seeded successfully")
    except Exception as e:
        print(f"Seeding skipped: {e}")
        db.rollback()
    finally:
        db.close()
