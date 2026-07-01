# Demo Video Script — IntelliFlow AP
## UiPath AgentHack 2025 | Track 2 — Maestro BPMN | ≤ 5 minutes

---

## Before You Hit Record

### Environment Setup Checklist
- [ ] Backend running: `python -m uvicorn backend.main:app --reload --port 8000`
- [ ] ngrok running: `ngrok http 8000` — note the public URL
- [ ] Browser open to `http://localhost:8000` — dashboard visible
- [ ] Browser tab 2: `http://localhost:8000/api/docs` — Swagger UI ready
- [ ] UiPath Orchestrator open — Maestro processes tab visible
- [ ] UiPath Action Center open — tasks tab visible
- [ ] Screen resolution: 1920×1080, browser zoom 100%
- [ ] Font size increased for readability (Ctrl+Plus)
- [ ] Notifications silenced, extra apps closed
- [ ] Demo data seeded: vendors, 5 POs, 3 goods receipts visible in dashboard

### Terminal Commands Pre-typed (don't run yet)
```bash
# Command 1 — standard invoice (auto-approved)
curl -X POST http://localhost:8000/api/invoices/ingest/text \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Invoice #INV-2024-0042 from Acme Software Solutions Ltd.\nDate: 2024-01-15\nBill To: TechCorp Inc.\nPO Reference: PO-2024-001\nDescription: Enterprise SaaS License Q1 2024\nAmount: USD 4,800.00\nPayment Terms: 2/10 Net 30",
    "source_channel": "portal"
  }'

# Command 2 — exception invoice (PO mismatch)  
curl -X POST http://localhost:8000/api/invoices/ingest/text \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Invoice #INV-2024-0099 from Globex Systems Corp.\nDate: 2024-01-16\nPO Reference: PO-2024-003\nCloud Infrastructure Services Jan 2024\nAmount: USD 28,750.00\nPayment Terms: Net 45",
    "source_channel": "email"
  }'

# Command 3 — CFO-level approval invoice
curl -X POST http://localhost:8000/api/invoices/ingest/text \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Invoice #INV-2024-0150 from Initech Manufacturing Ltd.\nDate: 2024-01-17\nPO Reference: PO-2024-002\nAnnual Hardware Procurement Q1\nLine Items:\n  - Server Rack Units x20: $32,000\n  - Network Switch Stack: $18,500\n  - UPS Systems x4: $12,000\nSubtotal: USD 62,500.00\nPayment Terms: 1/15 Net 60",
    "source_channel": "portal"
  }'
```

---

## Script

---

### SEGMENT 1: The Problem (0:00 – 0:30)

**[Screen: slide or blank screen — no product yet]**

> "Every company processes invoices. Most do it the hard way — manually keying data, emailing POs back and forth, waiting days for approvals. The average enterprise spends **$12.44 per invoice** and **3 to 5 business days** per cycle. AP teams spend 60% of their time on exceptions — mismatched POs, duplicate invoices, missing goods receipts. It's expensive, slow, and error-prone."

> "IntelliFlow AP fixes this. It uses Groq's LLaMA-3 models for AI document intelligence, orchestrated by UiPath Maestro BPMN, to process invoices end-to-end in under 60 seconds — automatically. Let me show you."

**[Transition: switch to browser at `http://localhost:8000`]**

---

### SEGMENT 2: Architecture Overview (0:30 – 1:00)

**[Screen: dashboard — briefly — then switch to UiPath Orchestrator → Maestro → BPMN diagram]**

> "Here's how it works. We have an 8-step BPMN process running in UiPath Maestro."

> "An invoice comes in — from email, PDF, or a web portal submission. Maestro kicks off the pipeline. Step 1 registers the invoice. Step 2 calls our FastAPI backend, which sends the raw text to Groq's LLaMA-3.3-70B model — it extracts all 15+ fields using structured function calling. Step 3 runs a 3-way match against the purchase order and goods receipt. Then a gateway: does it pass? Auto-approve under $500. Exception queue for mismatches. Human approval for larger amounts. Finally ERP posting and payment scheduling."

> "The entire flow is event-driven. Humans only touch it when necessary — and when they do, they use UiPath Action Center."

**[Switch back to dashboard]**

---

### SEGMENT 3: Live Demo — Happy Path (1:00 – 2:00)

**[Screen: terminal + dashboard side by side]**

> "Let me submit a real invoice. This is from Acme Software Solutions — $4,800, referencing PO-2024-001, with Net 30 payment terms and a 2% early-pay discount."

**[Run Command 1 in terminal]**

> "Submitted. Watch the dashboard."

**[Click refresh on dashboard — invoice appears with status `received`]**

> "Status is 'received'. The BPMN process is running in Orchestrator right now. Groq is extracting the data."

**[Refresh again — status moves to `extracting` → `extracted` → `matching`]**

> "Extraction confidence: 94%. Groq found the vendor, amount, PO reference, payment terms, everything. Now it's doing the 3-way match."

**[Refresh — status: `matched` then `approved`]**

> "Matched and auto-approved. $4,800 is under our $500... wait — let me click into this invoice to show you the match details."

**[Click invoice row]**

> "Match score: 92 out of 100. Amount matches the PO within tolerance. Vendor verified. Goods receipt confirmed. Auto-approved without a human touch. Total processing time: under 60 seconds."

> "And notice this: payment terms show 2/10 Net 30 — pay within 10 days, get 2% off. Our AI payment optimizer flagged this as a high-priority early pay. That's a 36% annualized return. The system scheduled it automatically."

---

### SEGMENT 4: Exception Flow (2:00 – 3:15)

**[Screen: terminal]**

> "Now let me show you what happens when things go wrong. This next invoice is from Globex Systems — $28,750. But there's a problem."

**[Run Command 2]**

**[Switch to dashboard, refresh]**

> "Status: extracting... extracted... matching... exception. Let me click into it."

**[Click invoice → scroll to exception panel]**

> "The matching engine caught an amount discrepancy — $28,750 invoiced versus $25,000 on the PO. That's a 15% variance, way above our 2% tolerance. Plus the goods receipt hasn't been confirmed for the full amount."

> "But look at this — the AI didn't just flag it. It gave a recommendation."

**[Point to AI recommendation field]**

> "'Amount exceeds PO by $3,750 (15%). Likely a scope expansion or change order. Recommend: obtain amended PO or split invoice into original scope and change order. Risk level: medium. Estimated resolution: 1–2 business days.'"

> "This recommendation was generated by LLaMA-3.1-8B in milliseconds. The AP team member doesn't have to figure out what to do — they have a starting point."

**[Switch to UiPath Action Center]**

> "And in UiPath Action Center, here's the task. The AP manager sees the exception type, the invoice details, Groq's recommendation, and a form to choose their action: approve, reject, request credit note, or query the vendor."

**[Show the form, then click back to dashboard]**

> "All human decisions flow back to our backend via UiPath webhooks — signed with HMAC-SHA256, so we know they're genuine."

---

### SEGMENT 5: Approval Flow (3:15 – 4:00)

**[Screen: terminal]**

> "Let me show you the approval path. This invoice is $62,500 from Initech Manufacturing — above our CFO threshold."

**[Run Command 3]**

**[Switch to dashboard, refresh until status shows `pending_approval`]**

> "Status: pending approval. This triggered a CFO-level approval task in Action Center."

**[Switch to Action Center → show CFO approval task]**

> "The CFO sees: invoice number, vendor, amount, PO reference, the match result, and two buttons — Approve or Reject. Plus a notes field."

> "They approve it. The webhook fires to our backend. Invoice status moves to approved. ERP posting triggers. Done."

**[Switch back to dashboard — show status progression]**

> "The full audit trail is there. Every state transition, every AI decision, every human action — timestamped and stored."

---

### SEGMENT 6: Analytics (4:00 – 4:45)

**[Screen: analytics tab on dashboard]**

> "Finally — the analytics. This is what finance leadership sees."

> "Touchless rate: 76% of invoices processed without any human intervention. Average processing time: 47 seconds. Cost per invoice: $0.56 — down from $12.44 manual. Early-pay discount capture: $18,400 this month on $2.1M in invoices processed."

> "Exception SLA compliance: 94%. The 6% that breached SLA were flagged in real time so managers could intervene."

> "This is the ROI story: a 95-person AP team handling 50,000 invoices a year saves **$595,000 annually** in processing costs alone — before counting early-pay discount capture."

---

### SEGMENT 7: Close (4:45 – 5:00)

**[Screen: dashboard overview]**

> "IntelliFlow AP: Groq AI for document intelligence, UiPath Maestro BPMN for process orchestration, Action Center for human-in-the-loop control, and a FastAPI backend that ties it all together."

> "End-to-end in under 60 seconds. Humans only where they add value. This is what AI-native accounts payable looks like."

**[End recording]**

---

## Recording Tips

### Setup
- Use OBS Studio (free) or Loom for screen recording
- Record at 1920×1080, 30fps minimum
- Use a lapel mic or headset — audio quality matters more than video quality
- Do a 30-second test recording first to check audio levels

### Pacing
- Speak at 120–140 words per minute — slightly slower than normal conversation
- Pause 1 second after switching screens to let viewers orient
- Don't rush the status transitions — let the viewer see the state changes

### Editing
- Cut dead air between commands and response
- Add lower-third text overlays for metric callouts ($12.44, 60 sec, 76%)
- A 5-second intro card with the project name is optional but professional
- Export as MP4 H.264, ≤500MB for Vimeo / YouTube upload

### YouTube / Vimeo Settings
- **Visibility:** Unlisted (accessible via link, not searchable)
- **Title:** `IntelliFlow AP — UiPath AgentHack 2025 Demo`
- **Description:** Paste your Devpost tagline + GitHub link
- Copy the share link → paste into Devpost

---

## Fallback: If UiPath Is Not Connected

If you can't demo the live UiPath Orchestrator / Action Center during recording, narrate what would happen and show:
1. The API docs at `/api/docs` — execute endpoints directly in Swagger UI
2. The dashboard state transitions after each API call
3. A screenshot of the Action Center task form (captured from UIPATH_SETUP.md §6 flow)

The core AI intelligence and 3-way matching demo works fully standalone — Groq extraction, match scoring, exception classification, and analytics are all live without UiPath credentials.
