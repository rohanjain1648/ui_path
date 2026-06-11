from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    app_env: str = "development"
    secret_key: str = "dev_secret_key_change_in_prod"
    database_url: str = "sqlite:///./intelliflow_ap.db"

    uipath_orchestrator_url: str = "https://cloud.uipath.com"
    uipath_tenant: str = ""
    uipath_client_id: str = ""
    uipath_client_secret: str = ""

    auto_approve_threshold: float = 500.0
    manager_approval_threshold: float = 10000.0
    cfo_approval_threshold: float = 50000.0

    po_match_tolerance_percent: float = 2.0
    line_item_tolerance_percent: float = 5.0

    claude_model: str = "claude-sonnet-4-6"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
