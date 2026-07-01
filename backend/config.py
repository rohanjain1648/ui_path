from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── Groq (free LLM) ──────────────────────────────────────────────────────
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"       # main reasoning + tool use
    groq_model_fast: str = "llama-3.1-8b-instant"     # fast text generation
    groq_model_vision: str = "llama-3.2-90b-vision-preview"  # image invoices

    # ── App ───────────────────────────────────────────────────────────────────
    app_env: str = "development"
    secret_key: str = "dev_secret_key_change_in_prod"
    database_url: str = "sqlite:///./intelliflow_ap.db"

    # ── UiPath Automation Cloud ───────────────────────────────────────────────
    uipath_orchestrator_url: str = "https://cloud.uipath.com"
    uipath_account_name: str = ""       # your account/org name
    uipath_tenant_name: str = ""        # tenant name (e.g. Default)
    uipath_client_id: str = ""
    uipath_client_secret: str = ""
    uipath_webhook_secret: str = ""     # for validating incoming UiPath webhooks
    uipath_process_key: str = ""        # release key for the BPMN process

    # ── Approval thresholds (USD) ─────────────────────────────────────────────
    auto_approve_threshold: float = 500.0
    manager_approval_threshold: float = 10000.0
    cfo_approval_threshold: float = 50000.0

    # ── Matching tolerances ───────────────────────────────────────────────────
    po_match_tolerance_percent: float = 2.0
    line_item_tolerance_percent: float = 5.0

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
