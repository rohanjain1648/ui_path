"""
AI intelligence layer powered by Groq (free tier).
Handles invoice extraction, anomaly detection, payment optimization,
and exception resolution using llama-3.3-70b-versatile via Groq's API.

Groq free tier limits (as of 2025):
  llama-3.3-70b-versatile : 6,000 TPM, 500 RPD
  llama-3.1-8b-instant    : 20,000 TPM, 14,400 RPD
  llama-3.2-90b-vision    : 7,000 TPM, 250 RPD (for image invoices)
"""
import json
import base64
from typing import Optional

from groq import Groq
from backend.config import get_settings

settings = get_settings()
client = Groq(api_key=settings.groq_api_key)

# ── Model selection ──────────────────────────────────────────────────────────

MODEL_MAIN = settings.groq_model          # llama-3.3-70b-versatile
MODEL_FAST = settings.groq_model_fast     # llama-3.1-8b-instant
MODEL_VISION = settings.groq_model_vision # llama-3.2-90b-vision-preview

# ── Tool definitions (OpenAI function-calling format) ────────────────────────

EXTRACTION_TOOL = {
    "type": "function",
    "function": {
        "name": "extract_invoice_data",
        "description": "Extract all structured fields from an invoice document with high precision.",
        "parameters": {
            "type": "object",
            "properties": {
                "vendor_name": {
                    "type": "string",
                    "description": "Legal vendor name exactly as printed on invoice"
                },
                "vendor_code": {
                    "type": "string",
                    "description": "Vendor code/ID if present on invoice"
                },
                "invoice_number": {
                    "type": "string",
                    "description": "Unique invoice identifier issued by vendor"
                },
                "invoice_date": {
                    "type": "string",
                    "description": "Invoice date in YYYY-MM-DD format"
                },
                "due_date": {
                    "type": "string",
                    "description": "Payment due date in YYYY-MM-DD format"
                },
                "total_amount": {
                    "type": "number",
                    "description": "Total invoice amount as a number, no currency symbols"
                },
                "subtotal_amount": {
                    "type": "number",
                    "description": "Subtotal before tax"
                },
                "tax_amount": {
                    "type": "number",
                    "description": "Total tax or VAT, 0 if none"
                },
                "currency": {
                    "type": "string",
                    "description": "ISO 4217 currency code: USD, EUR, GBP, INR, etc. Infer from symbols."
                },
                "payment_terms": {
                    "type": "string",
                    "description": "Payment terms string, e.g. 'net30', '2/10 net 30', 'due on receipt'"
                },
                "po_reference": {
                    "type": "string",
                    "description": "Purchase order number referenced on the invoice. Look for PO#, P.O., Purchase Order, Our Order, Ref."
                },
                "line_items": {
                    "type": "array",
                    "description": "All line items on the invoice",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "quantity": {"type": "number"},
                            "unit_price": {"type": "number"},
                            "total_price": {"type": "number"},
                            "unit_of_measure": {"type": "string"},
                            "product_code": {"type": "string"}
                        },
                        "required": ["description", "total_price"]
                    }
                },
                "bank_details": {
                    "type": "object",
                    "description": "Vendor payment/banking details if provided",
                    "properties": {
                        "bank_name": {"type": "string"},
                        "account_number": {"type": "string"},
                        "routing_number": {"type": "string"},
                        "iban": {"type": "string"},
                        "swift": {"type": "string"}
                    }
                },
                "remit_to_address": {
                    "type": "string",
                    "description": "Remittance address if different from vendor address"
                },
                "notes": {
                    "type": "string",
                    "description": "Special instructions or notes on the invoice"
                },
                "confidence_score": {
                    "type": "number",
                    "description": (
                        "Extraction confidence 0-100. Start at 100 and deduct: "
                        "-25 for each missing mandatory field (vendor_name, invoice_number, invoice_date, total_amount), "
                        "-10 for conflicting data, -5 for unusual formatting, -3 for each unclear optional field."
                    )
                },
                "extraction_warnings": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List any fields that were unclear, missing, or required inference"
                }
            },
            "required": [
                "vendor_name", "invoice_number", "invoice_date",
                "total_amount", "currency", "confidence_score"
            ]
        }
    }
}

ANOMALY_TOOL = {
    "type": "function",
    "function": {
        "name": "detect_invoice_anomalies",
        "description": "Analyze an invoice for fraud indicators, pricing anomalies, and policy violations.",
        "parameters": {
            "type": "object",
            "properties": {
                "anomaly_score": {
                    "type": "number",
                    "description": (
                        "Risk score 0-100. 0=clean, 100=definite fraud. "
                        "Thresholds: <20 low, 20-50 medium, 50-80 high, >80 critical. "
                        "Score conservatively — only score >50 with clear evidence."
                    )
                },
                "flags": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": [
                                    "round_number_bias", "duplicate_suspected",
                                    "bank_change_detected", "threshold_splitting",
                                    "unusual_vendor_category", "date_manipulation",
                                    "price_inflation", "phantom_vendor",
                                    "missing_gr", "policy_violation",
                                    "amount_exceeds_po", "unfamiliar_line_item"
                                ]
                            },
                            "severity": {
                                "type": "string",
                                "enum": ["low", "medium", "high", "critical"]
                            },
                            "description": {"type": "string"},
                            "evidence": {"type": "string"}
                        },
                        "required": ["type", "severity", "description"]
                    }
                },
                "recommended_action": {
                    "type": "string",
                    "enum": [
                        "auto_approve", "additional_review",
                        "human_required", "block_and_investigate"
                    ]
                },
                "reasoning": {
                    "type": "string",
                    "description": "Brief explanation of the overall risk assessment"
                }
            },
            "required": ["anomaly_score", "flags", "recommended_action", "reasoning"]
        }
    }
}

# ── System prompt strings ─────────────────────────────────────────────────────

_EXTRACTION_SYSTEM = (
    "You are IntelliFlow AP's invoice extraction engine. Your job is to parse invoice documents "
    "with extreme precision and return fully structured data using the extract_invoice_data function.\n\n"
    "RULES:\n"
    "- Always normalize dates to YYYY-MM-DD\n"
    "- Normalize currency to ISO 4217 ($ → USD, € → EUR, £ → GBP, ₹ → INR)\n"
    "- Detect payment terms: 'net 30', '2/10 net 30', 'due on receipt', 'COD'\n"
    "- PO references appear as: 'PO#', 'Purchase Order:', 'Ref:', 'Our Order:', 'P.O.'\n"
    "- Never hallucinate — if a field is absent, omit it or set to null\n"
    "- Sum line items to verify total_amount; flag discrepancies in extraction_warnings\n"
    "- ALWAYS call the extract_invoice_data function — never respond in plain text"
)

_ANOMALY_SYSTEM = (
    "You are IntelliFlow AP's fraud and anomaly detection engine. "
    "Analyze invoices against their matched PO and vendor history.\n\n"
    "FRAUD PATTERNS TO CHECK:\n"
    "1. round_number_bias: amounts ending in exactly .00 across multiple lines\n"
    "2. threshold_splitting: amounts just below $500, $10K, $50K approval thresholds\n"
    "3. bank_change_detected: different bank details vs vendor master record\n"
    "4. phantom_vendor: new vendor, no purchase history\n"
    "5. date_manipulation: invoice date predates the PO date\n"
    "6. price_inflation: unit prices >15% above PO agreed prices\n"
    "7. unfamiliar_line_item: goods/services not matching vendor's business category\n"
    "8. missing_gr: invoice submitted before goods receipt recorded\n\n"
    "Score conservatively. A clean invoice with one minor issue should score <20. "
    "ALWAYS call the detect_invoice_anomalies function."
)


# ── Helper: call Groq with function/tool use ──────────────────────────────────

def _call_with_tool(system: str, user_content, tool: dict, model: str = MODEL_MAIN) -> Optional[dict]:
    """
    Call Groq with a single tool definition and return the parsed tool arguments.
    Falls back to None if the model doesn't invoke the tool.
    """
    messages = [
        {"role": "system", "content": system},
    ]

    if isinstance(user_content, str):
        messages.append({"role": "user", "content": user_content})
    else:
        # list of content parts (for vision)
        messages.append({"role": "user", "content": user_content})

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=[tool],
        tool_choice="required",
        max_tokens=2048,
        temperature=0.1,  # low temp for deterministic extraction
    )

    message = response.choices[0].message
    if message.tool_calls:
        try:
            return json.loads(message.tool_calls[0].function.arguments)
        except (json.JSONDecodeError, AttributeError):
            return None
    return None


# ── Core extraction function ─────────────────────────────────────────────────

async def extract_invoice(
    invoice_text: str,
    invoice_image_b64: Optional[str] = None,
    media_type: str = "image/jpeg",
) -> dict:
    """
    Extract structured data from an invoice using Groq.
    Supports plain text and base64-encoded image (via llama vision model).
    """
    if invoice_image_b64 and MODEL_VISION:
        # Vision path: use llama-3.2-90b-vision-preview
        user_content = [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{media_type};base64,{invoice_image_b64}"
                }
            },
            {
                "type": "text",
                "text": (
                    "Extract all invoice data from this document using the "
                    "extract_invoice_data function. Be thorough and precise."
                )
            }
        ]
        result = _call_with_tool(_EXTRACTION_SYSTEM, user_content, EXTRACTION_TOOL, model=MODEL_VISION)
    else:
        user_content = (
            f"Extract all invoice data from the following document text using "
            f"the extract_invoice_data function:\n\n---\n{invoice_text}\n---"
        )
        result = _call_with_tool(_EXTRACTION_SYSTEM, user_content, EXTRACTION_TOOL)

    if result:
        return result

    # Fallback if tool calling failed
    return {
        "vendor_name": "UNKNOWN",
        "invoice_number": "UNKNOWN",
        "invoice_date": None,
        "total_amount": 0.0,
        "currency": "USD",
        "confidence_score": 0,
        "extraction_warnings": ["AI extraction failed — manual review required"],
    }


# ── Anomaly detection ─────────────────────────────────────────────────────────

async def detect_anomalies(
    invoice_data: dict,
    po_data: Optional[dict] = None,
    vendor_history: Optional[list] = None,
    vendor_master: Optional[dict] = None,
) -> dict:
    """
    Run fraud and anomaly detection on an extracted invoice using Groq.
    Returns anomaly_score (0–100) and structured flags.
    """
    context = {
        "invoice": invoice_data,
        "matched_po": po_data or {},
        "vendor_master": vendor_master or {},
        "vendor_invoice_history_last_10": vendor_history or [],
    }

    user_content = (
        f"Analyze the following invoice context for fraud and anomalies "
        f"using the detect_invoice_anomalies function:\n\n"
        f"```json\n{json.dumps(context, indent=2, default=str)}\n```"
    )

    result = _call_with_tool(_ANOMALY_SYSTEM, user_content, ANOMALY_TOOL)

    if result:
        return result

    return {
        "anomaly_score": 50,
        "flags": [{
            "type": "policy_violation",
            "severity": "medium",
            "description": "Anomaly detection failed — manual review required"
        }],
        "recommended_action": "human_required",
        "reasoning": "Detection engine error",
    }


# ── Payment optimization ─────────────────────────────────────────────────────

async def optimize_payment_timing(
    invoice_data: dict,
    company_cash_position: float = 1_000_000,
) -> dict:
    """
    Recommend optimal payment timing to capture early-pay discounts
    while respecting cash flow constraints.
    """
    prompt = (
        f"Invoice: {invoice_data.get('vendor_name')} | "
        f"Amount: {invoice_data.get('currency', 'USD')} {invoice_data.get('total_amount', 0):,.2f} | "
        f"Terms: {invoice_data.get('payment_terms', 'net30')} | "
        f"Due: {invoice_data.get('due_date', 'unknown')} | "
        f"Invoice date: {invoice_data.get('invoice_date', 'unknown')} | "
        f"Company cash available: ${company_cash_position:,.2f}\n\n"
        "Calculate and respond ONLY with a JSON object (no markdown):\n"
        '{"recommended_date": "YYYY-MM-DD", "discount_amount": 0.00, '
        '"discount_pct": 0.00, "annualized_roi": 0.00, "rationale": "..."}\n\n'
        "If terms are '2/10 net 30': 2% discount if paid within 10 days. "
        "Annualized ROI = (discount_pct / days_saved) * 365."
    )

    response = client.chat.completions.create(
        model=MODEL_FAST,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=256,
        temperature=0.1,
    )

    text = response.choices[0].message.content or "{}"
    try:
        # Strip any markdown fences
        text = text.strip().strip("```json").strip("```").strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        return json.loads(text[start:end]) if start != -1 else {}
    except (json.JSONDecodeError, ValueError):
        return {}


# ── Exception resolution advisor ─────────────────────────────────────────────

async def recommend_exception_resolution(
    exception_type: str,
    invoice_data: dict,
    po_data: Optional[dict],
    context_notes: str = "",
) -> str:
    """
    Generate a human-readable, actionable recommendation for resolving an AP exception.
    """
    prompt = (
        f"You are an AP expert. Write a 2-3 sentence recommendation for resolving this exception.\n\n"
        f"Exception Type: {exception_type}\n"
        f"Invoice: #{invoice_data.get('invoice_number')} from {invoice_data.get('vendor_name')}\n"
        f"Amount: {invoice_data.get('currency', 'USD')} {invoice_data.get('total_amount', 0):,.2f}\n"
        f"PO Reference: {invoice_data.get('po_reference', 'N/A')}\n"
        f"PO Amount: {po_data.get('total_amount', 'N/A') if po_data else 'N/A'}\n"
        f"Context: {context_notes}\n\n"
        "Be specific: what to verify, who to contact, what documentation to request. "
        "No bullet points — write as flowing sentences."
    )

    response = client.chat.completions.create(
        model=MODEL_FAST,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
        temperature=0.3,
    )

    return response.choices[0].message.content or "Manual review required."


# ── GL account classifier ─────────────────────────────────────────────────────

async def classify_gl_account(vendor_name: str, line_items: list) -> str:
    """
    Classify the appropriate GL account code from vendor name and line items.
    """
    items_text = "; ".join(
        item.get("description", "") for item in (line_items or [])[:5]
    )
    prompt = (
        f"Vendor: {vendor_name}\nLine items: {items_text}\n\n"
        "Select the best GL account code from this list and respond with ONLY the code:\n"
        "64000-Software-Licenses\n"
        "64500-Cloud-Infrastructure\n"
        "62000-Office-Supplies\n"
        "65000-Professional-Services\n"
        "63000-Travel-Entertainment\n"
        "66000-Marketing-Advertising\n"
        "67000-Facilities-Utilities\n"
        "69000-General-Operating-Expense"
    )

    response = client.chat.completions.create(
        model=MODEL_FAST,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=32,
        temperature=0.0,
    )

    text = (response.choices[0].message.content or "").strip()
    # Validate it's one of our codes
    valid_codes = [
        "64000-Software-Licenses", "64500-Cloud-Infrastructure",
        "62000-Office-Supplies", "65000-Professional-Services",
        "63000-Travel-Entertainment", "66000-Marketing-Advertising",
        "67000-Facilities-Utilities", "69000-General-Operating-Expense"
    ]
    return text if text in valid_codes else "69000-General-Operating-Expense"
