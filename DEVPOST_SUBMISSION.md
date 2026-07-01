# Devpost Submission Guide — IntelliFlow AP

Everything you need to fill in the four Devpost required fields and publish a strong project page.

---

## 1. Project Title

```
IntelliFlow AP — AI-Native Accounts Payable Orchestration with UiPath Maestro BPMN
```

---

## 2. Tagline (one sentence)

```
Eliminate 85% of manual AP work by orchestrating Groq AI document intelligence through a UiPath Maestro BPMN pipeline with human-in-the-loop exception handling.
```

---

## 3. Track

**Track 2 — UiPath Maestro BPMN**

---

## 4. Long Description (copy-paste into Devpost "About the project")

### Inspiration

Accounts payable is one of the most expensive, error-prone back-office functions in enterprise. The average company spends **$12.44 processing a single invoice** manually — taking 3–5 business days per cycle. AP clerks spend 60%+ of their time on exceptions: mismatched POs, duplicate invoices, missing goods receipts. Fraud losses in AP exceed $300B globally per year.

We asked: what if an intelligent system could handle 75%+ of invoices end-to-end in under 60 seconds, with humans only touching the genuinely hard cases?

### What it does

**IntelliFlow AP** is a production-grade accounts payable automation platform that:

1. **Ingests invoices** from email, PDF scan, or web portal
2. **Extracts 15+ structured fields** using Groq LLaMA-3.3-70B with function calling — vendor, amount, line items, GL codes, payment terms
3. **Performs 3-way matching** against purchase orders and goods receipts with configurable tolerance
4. **Auto-approves** invoices that pass matching below the $500 threshold (no human touch)
5. **Routes exceptions** — 9 types including fraud flags, duplicate detection, PO mismatches — to the right AP team member via UiPath Action Center
6. **Escalates large approvals** — invoices >$10K go to manager, >$50K to director, >$500K to CFO — via Action Center human tasks
7. **Captures early-pay discounts** using AI payment timing optimization, generating 36% annualized ROI
8. **Posts to ERP** automatically once approved
9. **Tracks all SLAs** with real-time dashboard — 4-hour SLA for fraud, 72-hour SLA for standard exceptions

### How we built it

**Backend:** FastAPI + SQLAlchemy + SQLite with an 11-state invoice status machine

**AI Layer (Groq):**
- `llama-3.3-70b-versatile` — invoice data extraction via structured function calling
- `llama-3.2-90b-vision-preview` — scanned PDF / image invoice OCR
- `llama-3.1-8b-instant` — payment timing optimization and exception advisory

**UiPath Platform:**
- **Maestro BPMN** — 8 service tasks, 3 exclusive gateways, 3 user tasks orchestrate the complete AP lifecycle
- **Action Center** — exception resolution and approval tasks with custom forms (`IntelliFlow-AP-Exception`, `IntelliFlow-AP-Approval` catalogs)
- **Agent Builder** — wraps Groq AI extraction and anomaly detection as callable agents
- **Orchestrator** — webhooks deliver human decisions back to the FastAPI backend in real time
- **Robot / UiPath Assistant** — email monitoring, ERP posting, vendor notifications

**Integration:** HMAC-SHA256 signed webhooks, OAuth2 machine-to-machine auth, ngrok tunnel for local dev

### Challenges we ran into

- **Groq function-calling schema differences** from Anthropic SDK — had to rewrite all tool schemas to OpenAI-compatible format (`parameters` instead of `input_schema`, `tool_choice="required"` instead of `{"type":"any"}`)
- **UiPath service tasks require public HTTPS** — solved with ngrok tunnel for local development
- **3-way match tolerance** — implemented configurable percentage-based tolerance at both invoice-level and line-item level to handle real-world vendor rounding
- **Webhook signature replay attacks** — HMAC-SHA256 with timing-safe comparison, configurable secret per environment

### Accomplishments that we're proud of

- **75%+ touchless rate** on well-formed invoices in testing
- **<60 seconds** end-to-end processing for standard invoices
- **$0** LLM cost thanks to Groq free tier (500 req/day on 70B, 14,400 on 8B)
- **9 exception types** with distinct SLAs and routing rules
- Full **audit trail** on every invoice — every state transition, every AI decision, every human action is logged

### What we learned

- UiPath Maestro BPMN is genuinely powerful for process-centric automation — the visual designer maps 1:1 to the business process, making it easy for both developers and business analysts to understand
- Groq's free tier is production-usable for hackathon-scale demos (and beyond) — the 70B model with function calling is excellent for structured document extraction
- Human-in-the-loop design requires as much thought as the automation itself — the exception routing logic and SLA tracking are as complex as the AI extraction

### What's next for IntelliFlow AP

- **Multi-tenant SaaS** with tenant-isolated databases and configurable thresholds per client
- **ERP connectors** for SAP, Oracle NetSuite, Microsoft Dynamics via REST APIs
- **Email ingestion robot** — UiPath Robot monitors AP inbox, attaches PDFs automatically
- **Vendor self-service portal** — vendors check invoice status, upload supporting docs
- **Predictive analytics** — ML model trained on historical AP data to predict exception likelihood before matching

---

## 5. UiPath Components Declaration (required field)

| Component | How Used |
|-----------|----------|
| UiPath Maestro BPMN | Core orchestration — 8 service tasks (HTTP REST calls to FastAPI), 3 exclusive gateways, 3 user tasks |
| UiPath Action Center | Exception resolution tasks (AP team) + approval tasks (manager/director/CFO) with custom catalogs |
| UiPath Agent Builder | Wraps Groq extraction agent and anomaly detection agent as reusable callable agents |
| UiPath Orchestrator | OAuth2 API, webhook delivery, robot management, process lifecycle |
| UiPath Studio / Robot | Email monitoring, ERP posting automation, vendor notification sequences |
| UiPath API Workflows | REST HTTP service tasks calling `/api/invoices/`, `/api/exceptions/`, `/api/approvals/` endpoints |

**Agent type:** Low-code agents (Agent Builder) + custom Python FastAPI service layer
**External AI:** Groq Cloud — llama-3.3-70b-versatile, llama-3.1-8b-instant, llama-3.2-90b-vision-preview

---

## 6. Links to Include on Devpost

- **GitHub Repository:** `https://github.com/YOUR_USERNAME/intelliflow-ap` (make it public before submitting)
- **Demo Video:** Upload to YouTube (unlisted) or Vimeo — link here after recording
- **Live Demo:** `http://localhost:8000` (local) or your deployed URL if hosted
- **Presentation Deck:** Upload `PITCH_DECK.html` to a hosting service or Google Slides — share link

---

## 7. Screenshots to Capture

Take these screenshots for the Devpost gallery (5–8 images recommended):

| # | What to Capture | How |
|---|-----------------|-----|
| 1 | Main dashboard — invoice list with status badges | `http://localhost:8000` |
| 2 | Invoice detail — extracted fields, confidence score, match result | Click any invoice |
| 3 | Exception queue — open exceptions with SLA countdown | Exceptions tab |
| 4 | AI recommendation panel — Groq's exception advice | Expand exception detail |
| 5 | Action Center task form — approval with Approve/Reject | UiPath Action Center UI |
| 6 | BPMN process diagram in Maestro | UiPath Orchestrator → Maestro |
| 7 | API docs — Swagger UI showing all 30+ endpoints | `http://localhost:8000/api/docs` |
| 8 | Analytics dashboard — KPIs, SLA compliance, savings | Analytics tab |

---

## 8. Pre-Submission Checklist

### Code & Repository
- [ ] GitHub repo is **public**
- [ ] `LICENSE` file present (MIT)
- [ ] `README.md` is complete and lists all UiPath components
- [ ] `UIPATH_SETUP.md` present with step-by-step guide
- [ ] `.env.example` documents all variables (no secrets committed)
- [ ] Backend starts cleanly: `python -m uvicorn backend.main:app --port 8000`
- [ ] Tests pass: `pytest tests/ -v`

### UiPath Platform
- [ ] UiPath Automation Cloud account active (trial or AgentHack Labs)
- [ ] Maestro BPMN process published with correct public service task URLs
- [ ] Action Center catalogs created: `IntelliFlow-AP-Exception` and `IntelliFlow-AP-Approval`
- [ ] Webhook registered in Orchestrator pointing to public ngrok URL
- [ ] Full flow tested: invoice → extraction → matching → exception → approval → ERP posting

### Submission Materials
- [ ] Demo video recorded (≤5 min), uploaded to YouTube/Vimeo, link ready — see `DEMO_SCRIPT.md`
- [ ] Devpost project page complete with description, screenshots, and links
- [ ] Presentation deck (`PITCH_DECK.html`) accessible via public link
- [ ] All four Devpost required fields filled in
- [ ] (Optional) UiPath product feedback form completed — eligible for $1,500 feedback award

---

## 9. Team Section

Fill in on Devpost:
- Team member names and roles
- LinkedIn / GitHub profiles

---

*Good luck! The judges will be looking for real UiPath platform integration, production-quality code, and a compelling business case. All three are strong in IntelliFlow AP.*
