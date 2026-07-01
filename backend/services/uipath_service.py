"""
UiPath Automation Cloud integration service.

Handles:
  - OAuth2 token acquisition and caching
  - Triggering BPMN process instances via Orchestrator Jobs API
  - Creating Action Center human tasks for exceptions and approvals
  - Reading task status and results
  - Webhook signature validation

UiPath REST API docs:
  https://docs.uipath.com/automation-cloud/docs/api-references
  https://cloud.uipath.com/{account}/{tenant}/orchestrator_/swagger
"""
import hashlib
import hmac
import time
import httpx
from typing import Optional
from backend.config import get_settings

settings = get_settings()

# ── Token cache (simple in-memory; use Redis in production) ──────────────────

_token_cache: dict = {"access_token": None, "expires_at": 0}


def _get_auth_token() -> str:
    """
    Acquire or return cached UiPath OAuth2 access token.
    Uses Client Credentials flow (machine-to-machine).
    """
    now = time.time()
    if _token_cache["access_token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"]

    url = "https://cloud.uipath.com/identity_/connect/token"
    resp = httpx.post(
        url,
        data={
            "grant_type": "client_credentials",
            "client_id": settings.uipath_client_id,
            "client_secret": settings.uipath_client_secret,
            "scope": "OR.Tasks OR.Robots OR.Execution OR.Webhooks",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = now + data.get("expires_in", 3600)
    return _token_cache["access_token"]


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_auth_token()}",
        "Content-Type": "application/json",
        "X-UIPATH-TenantName": settings.uipath_tenant_name,
    }


def _base_url() -> str:
    return (
        f"{settings.uipath_orchestrator_url}/"
        f"{settings.uipath_account_name}/"
        f"{settings.uipath_tenant_name}/orchestrator_/api"
    )


# ── Process / Job management ─────────────────────────────────────────────────

def trigger_bpmn_process(invoice_id: str, extra_vars: Optional[dict] = None) -> dict:
    """
    Start a new instance of the IntelliFlow AP BPMN process in Maestro.
    Passes invoice_id as the initial process variable.

    Returns the job details including job_id and status.
    """
    if not settings.uipath_process_key:
        return {"status": "skipped", "reason": "UIPATH_PROCESS_KEY not configured"}

    payload = {
        "startInfo": {
            "ReleaseKey": settings.uipath_process_key,
            "JobsCount": 1,
            "Strategy": "All",
            "InputArguments": {
                "invoice_id": invoice_id,
                "backend_url": "http://localhost:8000",   # replace with your public URL
                **(extra_vars or {}),
            }
        }
    }

    resp = httpx.post(
        f"{_base_url()}/odata/Jobs/UiPath.Server.Configuration.OData.StartJobs",
        json=payload,
        headers=_headers(),
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def get_job_status(job_id: str) -> dict:
    """Get the current status of a running process instance."""
    resp = httpx.get(
        f"{_base_url()}/odata/Jobs({job_id})",
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


# ── Action Center — Human Tasks ──────────────────────────────────────────────

def create_exception_task(
    invoice_id: str,
    invoice_number: str,
    vendor_name: str,
    amount: float,
    currency: str,
    exception_type: str,
    exception_description: str,
    ai_recommendation: str,
    assigned_to: str,
) -> dict:
    """
    Create a human task in UiPath Action Center for AP exception resolution.
    The assigned AP team member will see this task in their Action Center queue.
    """
    payload = {
        "taskData": {
            "Title": f"AP Exception: {exception_type.replace('_', ' ').title()} — {invoice_number}",
            "Priority": _map_exception_priority(exception_type),
            "TaskCatalogName": "IntelliFlow-AP-Exception",
            "AssignedToUser": assigned_to,
            "Data": {
                "invoice_id": invoice_id,
                "invoice_number": invoice_number,
                "vendor_name": vendor_name,
                "amount": f"{currency} {amount:,.2f}",
                "exception_type": exception_type,
                "description": exception_description,
                "ai_recommendation": ai_recommendation,
                "resolve_url": f"http://localhost:8000/api/exceptions",
                "dashboard_url": f"http://localhost:8000",
            }
        }
    }

    if not settings.uipath_client_id:
        return {"status": "skipped", "reason": "UiPath not configured — task logged locally only"}

    try:
        resp = httpx.post(
            f"{_base_url()}/tasks/TaskForms",
            json=payload,
            headers=_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        return {"status": "error", "detail": str(e)}


def create_approval_task(
    invoice_id: str,
    invoice_number: str,
    vendor_name: str,
    amount: float,
    currency: str,
    approval_level: str,
    approver_email: str,
    po_reference: Optional[str] = None,
) -> dict:
    """
    Create an approval task in UiPath Action Center.
    The approver (manager/director/CFO) will see an Approve/Reject form.
    """
    payload = {
        "taskData": {
            "Title": f"Invoice Approval Required: {invoice_number} — {currency} {amount:,.2f}",
            "Priority": "High",
            "TaskCatalogName": "IntelliFlow-AP-Approval",
            "AssignedToUser": approver_email,
            "Data": {
                "invoice_id": invoice_id,
                "invoice_number": invoice_number,
                "vendor_name": vendor_name,
                "amount": f"{currency} {amount:,.2f}",
                "approval_level": approval_level.upper(),
                "po_reference": po_reference or "N/A",
                "approval_api": f"http://localhost:8000/api/approvals",
                "dashboard_url": f"http://localhost:8000",
            }
        }
    }

    if not settings.uipath_client_id:
        return {"status": "skipped", "reason": "UiPath not configured — approval logged locally only"}

    try:
        resp = httpx.post(
            f"{_base_url()}/tasks/TaskForms",
            json=payload,
            headers=_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        return {"status": "error", "detail": str(e)}


def get_task_status(task_id: str) -> dict:
    """Get the current status of an Action Center task."""
    if not settings.uipath_client_id:
        return {"status": "skipped"}

    resp = httpx.get(
        f"{_base_url()}/tasks/TaskForms/{task_id}",
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


# ── Webhook validation ────────────────────────────────────────────────────────

def validate_webhook_signature(payload_bytes: bytes, signature_header: str) -> bool:
    """
    Validate that an incoming webhook is genuinely from UiPath Orchestrator.
    UiPath signs webhooks with HMAC-SHA256 using the shared webhook secret.

    Header format: "sha256=<hex_digest>"
    """
    if not settings.uipath_webhook_secret:
        return True  # skip validation if not configured (dev mode)

    expected = hmac.new(
        settings.uipath_webhook_secret.encode(),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()

    received = signature_header.replace("sha256=", "").strip()
    return hmac.compare_digest(expected, received)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _map_exception_priority(exception_type: str) -> str:
    high_priority = {"fraud_flag", "duplicate_invoice"}
    if exception_type.lower() in high_priority:
        return "High"
    return "Medium"


def is_configured() -> bool:
    """Return True if UiPath credentials are present."""
    return bool(settings.uipath_client_id and settings.uipath_client_secret)
