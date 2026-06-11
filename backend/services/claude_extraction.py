"""
Invoice extraction and anomaly detection using Claude claude-sonnet-4-6.
Uses tool_use for structured output and prompt caching on the system prompt.
"""
import json
import anthropic
from typing import Optional
from backend.config import get_settings

settings = get_settings()
client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

# ── Tool definitions ─────────────────────────────────────────────────────────

EXTRACTION_TOOL = {
    "name": "extract_invoice_data",
    "description": "Extract all structured fields from an invoice document with high precision.",
    "input_schema": {
        "type": "object",
        "properties": {
            "vendor_name": {"type": "string", "description": "Legal vendor name as printed on invoice"},
            "vendor_code": {"type": "string", "description": "Vendor code/ID if present"},
            "invoice_number": {"type": "string", "description": "Unique invoice identifier from vendor"},
            "invoice_date": {"type": "string", "description": "Invoice date in YYYY-MM-DD format"},
            "due_date": {"type": "string", "description": "Payment due date in YYYY-MM-DD format, null if not found"},
            "total_amount": {"type": "number", "description": "Total invoice amount (numeric only)"},
            "subtotal_amount": {"type": "number", "description": "Subtotal before tax"},
            "tax_amount": {"type": "number", "description": "Total tax/VAT amount, 0 if none"},
            "currency": {"type": "string", "description": "ISO 4217 currency code (USD, EUR, GBP, etc.)"},
            "payment_terms": {"type": "string", "description": "Payment terms string (e.g. 'net30', '2/10 net 30')"},
            "po_reference": {"type": "string", "description": "Purchase order number referenced on invoice, null if absent"},
            "line_items": {
                "type": "array",
                "description": "Individual line items on the invoice",
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
                "description": "Vendor bank/payment details if provided",
                "properties": {
                    "bank_name": {"type": "string"},
                    "account_number": {"type": "string"},
                    "routing_number": {"type": "string"},
                    "iban": {"type": "string"},
                    "swift": {"type": "string"}
                }
            },
            "remit_to_address": {"type": "string", "description": "Remittance address if different from vendor address"},
            "notes": {"type": "string", "description": "Any special instructions or notes on the invoice"},
            "confidence_score": {
                "type": "number",
                "description": "0-100 extraction confidence. Deduct points for: illegible text (-20), missing mandatory fields (-15 each), conflicting data (-10), unusual formatting (-5)."
            },
            "extraction_warnings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List any fields that were unclear, missing, or required inference"
            }
        },
        "required": ["vendor_name", "invoice_number", "invoice_date", "total_amount", "currency", "confidence_score"]
    }
}

ANOMALY_TOOL = {
    "name": "detect_invoice_anomalies",
    "description": "Analyze invoice for fraud indicators, pricing anomalies, and policy violations.",
    "input_schema": {
        "type": "object",
        "properties": {
            "anomaly_score": {
                "type": "number",
                "description": "0-100 risk score. 0=clean, 100=definite fraud. Thresholds: <20 low, 20-50 medium, 50-80 high, >80 critical."
            },
            "flags": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": [
                                "round_number_bias", "duplicate_suspected", "bank_change_detected",
                                "threshold_splitting", "unusual_vendor_category", "date_manipulation",
                                "price_inflation", "phantom_vendor", "missing_gr", "policy_violation",
                                "amount_exceeds_po", "unfamiliar_line_item"
                            ]
                        },
                        "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                        "description": {"type": "string"},
                        "evidence": {"type": "string"}
                    },
                    "required": ["type", "severity", "description"]
                }
            },
            "recommended_action": {
                "type": "string",
                "enum": ["auto_approve", "additional_review", "human_required", "block_and_investigate"]
            },
            "reasoning": {"type": "string", "description": "Brief explanation of the overall risk assessment"}
        },
        "required": ["anomaly_score", "flags", "recommended_action", "reasoning"]
    }
}

# ── Cached system prompts ────────────────────────────────────────────────────

EXTRACTION_SYSTEM = [
    {
        "type": "text",
        "text": (
            "You are IntelliFlow AP's invoice extraction engine. Your job is to parse invoice documents "
            "with extreme precision and return fully structured data using the extract_invoice_data tool.\n\n"
            "RULES:\n"
            "- Always normalize dates to YYYY-MM-DD\n"
            "- Always normalize currency to ISO 4217 (infer from symbols: $ → USD, € → EUR, £ → GBP)\n"
            "- Detect payment terms patterns: 'net 30', '2/10 net 30', 'due on receipt', 'COD'\n"
            "- PO references appear as: 'PO#', 'Purchase Order:', 'Ref:', 'Our Order:', 'P.O.'\n"
            "- Calculate confidence_score rigorously: mandatory fields (vendor, invoice#, date, amount) = 25pts each\n"
            "- If invoice_number cannot be found, use 'UNKNOWN-' + first 8 chars of vendor name\n"
            "- Never hallucinate data — if a field is absent, omit it or use null\n"
            "- Sum line items to verify total_amount consistency; flag discrepancies in extraction_warnings"
        ),
        "cache_control": {"type": "ephemeral"},
    }
]

ANOMALY_SYSTEM = [
    {
        "type": "text",
        "text": (
            "You are IntelliFlow AP's fraud and anomaly detection engine. Analyze invoices against their "
            "matched PO and vendor history to detect financial fraud, pricing abuse, and policy violations.\n\n"
            "FRAUD PATTERNS TO CHECK:\n"
            "1. Round number bias: amounts ending in exactly .00 across multiple line items\n"
            "2. Threshold splitting: amounts just below $500, $10K, $50K approval thresholds\n"
            "3. Bank account change: different bank details vs. vendor master\n"
            "4. Phantom vendor: no purchase history, unusual registration date\n"
            "5. Date manipulation: invoice date predates PO date\n"
            "6. Price inflation: unit prices >15% above PO agreed prices\n"
            "7. Unfamiliar line items: goods/services not matching vendor's category\n"
            "8. Missing GR: invoice submitted before goods receipt recorded\n\n"
            "Score conservatively. A clean invoice with one minor issue should score <20. "
            "Only score >80 for clear fraud indicators with multiple corroborating signals."
        ),
        "cache_control": {"type": "ephemeral"},
    }
]


# ── Core extraction function ─────────────────────────────────────────────────

async def extract_invoice(
    invoice_text: str,
    invoice_image_b64: Optional[str] = None,
    media_type: str = "image/jpeg",
) -> dict:
    """
    Extract structured data from an invoice using Claude.
    Supports both plain text and base64-encoded image input.
    """
    if invoice_image_b64:
        user_content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": invoice_image_b64,
                },
            },
            {
                "type": "text",
                "text": "Extract all invoice data from this document using the extract_invoice_data tool.",
            },
        ]
    else:
        user_content = (
            f"Extract all invoice data from the following document text:\n\n"
            f"---\n{invoice_text}\n---\n\n"
            "Use the extract_invoice_data tool to return structured data."
        )

    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=2048,
        system=EXTRACTION_SYSTEM,
        tools=[EXTRACTION_TOOL],
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": user_content}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_invoice_data":
            return block.input

    return {
        "vendor_name": "UNKNOWN",
        "invoice_number": "UNKNOWN",
        "invoice_date": None,
        "total_amount": 0.0,
        "currency": "USD",
        "confidence_score": 0,
        "extraction_warnings": ["Claude did not return tool_use — manual review required"],
    }


# ── Anomaly detection ────────────────────────────────────────────────────────

async def detect_anomalies(
    invoice_data: dict,
    po_data: Optional[dict] = None,
    vendor_history: Optional[list] = None,
    vendor_master: Optional[dict] = None,
) -> dict:
    """
    Run anomaly and fraud detection on an extracted invoice.
    Returns anomaly_score (0-100) and structured flags.
    """
    context = {
        "invoice": invoice_data,
        "matched_po": po_data or {},
        "vendor_master": vendor_master or {},
        "vendor_invoice_history_last_10": vendor_history or [],
    }

    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=1024,
        system=ANOMALY_SYSTEM,
        tools=[ANOMALY_TOOL],
        tool_choice={"type": "any"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"Analyze the following invoice context for fraud and anomalies:\n\n"
                    f"```json\n{json.dumps(context, indent=2, default=str)}\n```\n\n"
                    "Use the detect_invoice_anomalies tool to return your assessment."
                ),
            }
        ],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "detect_invoice_anomalies":
            return block.input

    return {
        "anomaly_score": 50,
        "flags": [{"type": "policy_violation", "severity": "medium", "description": "Anomaly detection failed — manual review required"}],
        "recommended_action": "human_required",
        "reasoning": "Detection engine error",
    }


# ── Payment term optimizer ───────────────────────────────────────────────────

async def optimize_payment_timing(
    invoice_data: dict,
    company_cash_position: float = 1_000_000,
) -> dict:
    """
    Use Claude to recommend optimal payment timing to maximize early-pay discounts
    while respecting cash flow constraints.
    """
    prompt = (
        f"Invoice: {invoice_data.get('vendor_name')} | "
        f"Amount: {invoice_data.get('currency', 'USD')} {invoice_data.get('total_amount', 0):,.2f} | "
        f"Terms: {invoice_data.get('payment_terms', 'net30')} | "
        f"Due: {invoice_data.get('due_date', 'unknown')} | "
        f"Company cash available: ${company_cash_position:,.2f}\n\n"
        "Calculate: (1) early payment discount amount if terms allow, "
        "(2) optimal payment date, (3) annualized ROI of early payment vs holding cash. "
        "Return JSON: {recommended_date, discount_amount, discount_pct, annualized_roi, rationale}"
    )

    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text if response.content else "{}"
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        return json.loads(text[start:end]) if start != -1 else {}
    except (json.JSONDecodeError, ValueError):
        return {}


# ── Exception resolution recommender ────────────────────────────────────────

async def recommend_exception_resolution(
    exception_type: str,
    invoice_data: dict,
    po_data: Optional[dict],
    context_notes: str = "",
) -> str:
    """
    Generate a human-readable recommendation for resolving an AP exception.
    """
    prompt = (
        f"AP Exception Type: {exception_type}\n"
        f"Invoice: #{invoice_data.get('invoice_number')} from {invoice_data.get('vendor_name')}\n"
        f"Invoice Amount: {invoice_data.get('currency', 'USD')} {invoice_data.get('total_amount', 0):,.2f}\n"
        f"PO Reference: {invoice_data.get('po_reference', 'N/A')}\n"
        f"PO Amount: {po_data.get('total_amount', 'N/A') if po_data else 'N/A'}\n"
        f"Additional context: {context_notes}\n\n"
        "Provide a concise 2-3 sentence recommendation for how the AP team should resolve this exception. "
        "Be specific about what to verify, who to contact, and what documentation to request."
    )

    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text if response.content else "Manual review required."
