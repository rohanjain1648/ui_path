# UiPath Automation Cloud — Complete Setup Guide

This guide takes you from zero to a running UiPath Maestro BPMN process connected to IntelliFlow AP.

---

## Table of Contents

1. [Create Your UiPath Account](#1-create-your-uipath-account)
2. [Request UiPath Labs Access (Hackathon)](#2-request-uipath-labs-access-hackathon)
3. [Configure API Credentials](#3-configure-api-credentials)
4. [Expose Your Local Backend (ngrok)](#4-expose-your-local-backend-ngrok)
5. [Set Up Maestro BPMN Process](#5-set-up-maestro-bpmn-process)
6. [Configure Action Center Task Catalogs](#6-configure-action-center-task-catalogs)
7. [Set Up Webhooks (UiPath → Your Backend)](#7-set-up-webhooks-uipath--your-backend)
8. [Set Up the RPA Robot](#8-set-up-the-rpa-robot)
9. [Test the End-to-End Flow](#9-test-the-end-to-end-flow)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Create Your UiPath Account

1. Go to **https://cloud.uipath.com**
2. Click **Start Trial** → sign up with your email
3. You get a **60-day Enterprise Trial** — enough for the hackathon
4. Choose your organization name (e.g. `intelliflow-ap`) — this becomes `UIPATH_ACCOUNT_NAME` in `.env`
5. Your default tenant is usually `DefaultTenant` — this becomes `UIPATH_TENANT_NAME`

> **Hackathon participants:** Use the UiPath Labs link from your registration confirmation email to get pre-provisioned credentials with AI units included. Skip the trial signup if you have Labs credentials.

---

## 2. Request UiPath Labs Access (Hackathon)

If you're registered for AgentHack:

1. One team member fills out the **UiPath Labs access form** (link in your hackathon confirmation email)
2. Within **3 business days** you receive a separate email with:
   - UiPath Labs URL
   - Pre-configured tenant credentials
   - AI units for Agent Builder and Maestro
3. Use those credentials in your `.env` — do **not** create a separate trial account

---

## 3. Configure API Credentials

### 3a. Create an External Application (OAuth2)

This allows IntelliFlow AP backend to call UiPath APIs programmatically.

1. In UiPath Automation Cloud, go to **Admin** (top-right gear icon)
2. Select your **Organization** → click **External Applications**
3. Click **Add Application**
4. Fill in:
   - **Name:** `IntelliFlow AP Backend`
   - **Application Type:** Confidential application
5. Under **Scopes**, add:
   - `OR.Tasks` (read/write Action Center tasks)
   - `OR.Robots` (trigger robot jobs)
   - `OR.Execution` (start process instances)
   - `OR.Webhooks` (manage webhooks)
6. Click **Add** → copy the **Client ID** and **Client Secret** (shown only once!)

### 3b. Update Your .env

```env
UIPATH_ORCHESTRATOR_URL=https://cloud.uipath.com
UIPATH_ACCOUNT_NAME=your_org_name          # from step 1
UIPATH_TENANT_NAME=DefaultTenant           # or your tenant name
UIPATH_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
UIPATH_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 3c. Verify API Access

```bash
# Test token acquisition
python -c "
from backend.services.uipath_service import _get_auth_token
token = _get_auth_token()
print('Token acquired:', token[:20] + '...')
"
```

---

## 4. Expose Your Local Backend (ngrok)

UiPath Orchestrator needs a **public HTTPS URL** to call your FastAPI service tasks and deliver webhooks. Use ngrok for local development.

### Install ngrok

```bash
# Windows (PowerShell)
winget install ngrok

# Or download from https://ngrok.com/download
```

### Start tunnel

```bash
# In a separate terminal (keep running throughout development)
ngrok http 8000

# Output example:
# Forwarding  https://abc123def456.ngrok-free.app -> http://localhost:8000
# Copy the https:// URL — this is your PUBLIC_URL
```

### Update your .env

```env
# Add this line (replace with your actual ngrok URL)
PUBLIC_URL=https://abc123def456.ngrok-free.app
```

> **Tip:** ngrok free tier gives a new URL every time you restart. For stable URLs during the hackathon, either upgrade ngrok or deploy the backend to a free cloud platform (Railway, Render, Fly.io).

---

## 5. Set Up Maestro BPMN Process

### 5a. Enable Maestro in Your Tenant

1. Go to **Admin** → **Tenants** → click your tenant → **Features**
2. Enable **Maestro** (may be called "Process Orchestration")
3. Enable **Maestro BPMN** if shown separately

### 5b. Create the BPMN Process

1. In your tenant, go to **Maestro** → **Processes** → **Create New**
2. Select **BPMN Process**
3. Name it: `IntelliFlow AP - Invoice Processing`

### 5c. Build the BPMN Diagram

Add these elements in the visual designer (refer to `uipath/bpmn/intelliflow_ap_process.json` for the full spec):

#### Start Events (Message Start)
- `Invoice Received via Email`
- `Invoice Submitted via Portal`

#### Service Tasks (HTTP)

For each service task, set **Implementation = REST HTTP**:

| Task Name | Method | URL |
|-----------|--------|-----|
| Ingest & Register | POST | `{PUBLIC_URL}/api/invoices/ingest/text` |
| AI Extract Data | POST | `{PUBLIC_URL}/api/invoices/{invoice_id}/extract` |
| 3-Way PO Match | POST | `{PUBLIC_URL}/api/invoices/{invoice_id}/match` |
| Post to ERP | POST | `{PUBLIC_URL}/api/invoices/{invoice_id}/post-erp` |

For each task, map the JSON response fields to process variables:
```
# Example: "AI Extract Data" output mapping
$.extraction_confidence  → extraction_confidence (number)
$.status                 → invoice_status (string)
$.po_reference           → po_reference (string)
```

#### Exclusive Gateways

**Quality Gate** (after extraction):
- `extraction_confidence >= 70` → continue to 3-Way Match
- default → Manual Data Entry (User Task)

**Match Result Gateway** (after matching):
- `auto_approvable == true` → Post to ERP
- `matched == true` → Approval User Task
- default → Exception User Task

#### User Tasks (Action Center)

| Task Name | Assignee | Form |
|-----------|----------|------|
| Manual Data Entry | `ap_team@company.com` | Text fields for invoice data |
| AP Exception Resolution | Dynamic (from variable) | Dropdown: approve/reject/query + notes |
| Manager Approval | Dynamic (from variable) | Approve / Reject buttons + notes |

#### End Events
- `Invoice Processed` (success)
- `Invoice Rejected` (rejection path)

### 5d. Get the Process Release Key

1. After saving and publishing the process, go to **Orchestrator** → **Processes**
2. Find `IntelliFlow AP - Invoice Processing`
3. Copy the **Release Key** (UUID)
4. Add to `.env`: `UIPATH_PROCESS_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`

---

## 6. Configure Action Center Task Catalogs

Action Center needs task catalogs defined before tasks can be created.

### 6a. Create Exception Task Catalog

1. Go to **Action Center** → **Task Catalogs** → **New Catalog**
2. Name: `IntelliFlow-AP-Exception`
3. Add input data fields:
   - `invoice_id` (Text)
   - `invoice_number` (Text)
   - `vendor_name` (Text)
   - `amount` (Text)
   - `exception_type` (Text)
   - `description` (Long Text)
   - `ai_recommendation` (Long Text)
4. Add output fields (what the human fills in):
   - `action` (Select: approve, reject, request_credit_note, vendor_query, amend_po)
   - `resolution_notes` (Long Text, required)

### 6b. Create Approval Task Catalog

1. Go to **Action Center** → **Task Catalogs** → **New Catalog**
2. Name: `IntelliFlow-AP-Approval`
3. Add input data fields:
   - `invoice_id`, `invoice_number`, `vendor_name`, `amount`, `approval_level`, `po_reference`
4. Add output fields:
   - `approved` (Boolean — renders as Approve/Reject buttons)
   - `notes` (Long Text)

---

## 7. Set Up Webhooks (UiPath → Your Backend)

Webhooks let UiPath notify your backend when a human completes a task.

### 7a. Generate a Webhook Secret

```bash
python -c "import secrets; print(secrets.token_hex(32))"
# Copy the output → UIPATH_WEBHOOK_SECRET in .env
```

### 7b. Register the Webhook in UiPath

1. In Orchestrator, go to **Settings** → **Webhooks** → **Add**
2. Fill in:
   - **URL:** `https://your-ngrok-url.ngrok-free.app/api/webhooks/uipath`
   - **Secret:** paste your `UIPATH_WEBHOOK_SECRET`
   - **Subscribe to events:**
     - ✅ `task.completed` (human finishes an Action Center task)
     - ✅ `job.completed` (robot job finishes)
     - ✅ `job.faulted` (robot job fails — for error handling)
3. Click **Save** → UiPath sends a verification GET request to your URL
4. Verify the endpoint is reachable: `GET /api/webhooks/uipath` should return `{"status": "ok"}`

### 7c. Verify Signature Validation

```bash
# Test your webhook receiver is up
curl https://your-ngrok-url.ngrok-free.app/api/webhooks/uipath
# Should return: {"status": "ok", "service": "IntelliFlow AP Webhook Receiver"}
```

---

## 8. Set Up the RPA Robot

For email monitoring and ERP integration you need a UiPath robot.

### 8a. Install UiPath Assistant

1. Download UiPath Assistant from the Orchestrator → **Robots** → **Download** section
2. Install on your local machine (Windows only)
3. Connect to your tenant: open Assistant → Settings → enter your Orchestrator URL and machine key

### 8b. Create a Machine in Orchestrator

1. Go to **Orchestrator** → **Machines** → **Add Machine**
2. Type: Standard Machine
3. Name: `IntelliFlow-Dev-Machine`
4. Copy the **Machine Key**
5. Paste into UiPath Assistant → Settings → Machine Key

### 8c. Create a Robot Record

1. Go to **Orchestrator** → **Robots** → **Add Robot**
2. Type: Unattended
3. Machine: select `IntelliFlow-Dev-Machine`
4. Username: your Windows username (e.g. `DESKTOP-ABC\YourName`)

### 8d. Deploy Email Monitor Process (Optional)

For demo purposes, you can trigger invoices manually via the dashboard instead of setting up email monitoring. Skip this for the initial hackathon demo.

---

## 9. Test the End-to-End Flow

### Step 1: Start the backend

```bash
python -m uvicorn backend.main:app --reload --port 8000
```

### Step 2: Start ngrok

```bash
ngrok http 8000
```

### Step 3: Trigger a test invoice

```bash
curl -X POST http://localhost:8000/api/invoices/ingest/text \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Invoice #INV-TEST-001 from Acme Software Solutions Ltd.\nDate: 2024-01-15\nPO: PO-2024-001\nTotal: $15,600.00\nTerms: 2/10 Net 30",
    "source_channel": "portal"
  }'
```

### Step 4: Watch the pipeline

1. Open the dashboard at `http://localhost:8000`
2. The invoice moves through: `received → extracting → extracted → matching → matched`
3. If the UiPath process key is configured, a BPMN instance is also triggered in Orchestrator

### Step 5: Simulate an exception

```bash
# Submit an invoice with no PO reference (will create an exception)
curl -X POST http://localhost:8000/api/invoices/ingest/text \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Invoice #INV-NO-PO from Unknown Vendor\nDate: 2024-01-15\nTotal: $49,950.00",
    "source_channel": "email"
  }'
```

This creates a `PO_NOT_FOUND` exception → appears in the dashboard exception queue → (if UiPath is configured) creates an Action Center task for the AP team.

### Step 6: Resolve via dashboard

Click **Resolve** next to the exception in the dashboard — this calls `POST /api/exceptions/{id}/resolve`.

---

## 10. Troubleshooting

| Problem | Solution |
|---------|----------|
| `401 Unauthorized` from UiPath API | Token expired or wrong client_id/secret — re-check `.env` |
| Webhook not received | Check ngrok is running; verify URL in UiPath Orchestrator Settings → Webhooks |
| `422 Validation Error` on webhook | Check the event JSON format in UiPath docs; the `Type` field varies by event |
| Maestro BPMN not visible | Enable it in Admin → Tenants → Features; may need Labs access |
| Action Center tasks not appearing | Verify task catalog names match exactly: `IntelliFlow-AP-Exception` / `IntelliFlow-AP-Approval` |
| Groq rate limit hit | Free tier is 500 req/day on 70B model; switch heavy calls to `llama-3.1-8b-instant` |
| `UIPATH_PROCESS_KEY not configured` | Normal for local dev — backend works standalone; add key only after BPMN is published |

---

## Environment Variables Summary

```env
# Required for AI (get free key at console.groq.com)
GROQ_API_KEY=gsk_...

# Required for UiPath integration
UIPATH_ORCHESTRATOR_URL=https://cloud.uipath.com
UIPATH_ACCOUNT_NAME=your_org_name
UIPATH_TENANT_NAME=DefaultTenant
UIPATH_CLIENT_ID=xxxx
UIPATH_CLIENT_SECRET=xxxx
UIPATH_WEBHOOK_SECRET=xxxx
UIPATH_PROCESS_KEY=xxxx   # after BPMN is published

# Optional (defaults work for local dev)
AUTO_APPROVE_THRESHOLD=500
MANAGER_APPROVAL_THRESHOLD=10000
CFO_APPROVAL_THRESHOLD=50000
PO_MATCH_TOLERANCE_PERCENT=2.0
```
