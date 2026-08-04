from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    database_url: str
    log_level: str = "INFO"

    # --- Proveedor LLM (D10: dev = opencode/Anthropic-compatible, despliegue = Claude) ---
    llm_provider: str = "anthropic"
    anthropic_api_base: str = "https://api.anthropic.com"
    anthropic_api_key: str = ""
    anthropic_model: str = ""

    # --- Embeddings (Gemini) ---
    gemini_api_key: str = ""
    embedding_model: str = "gemini-embedding-2"
    embedding_dim: int = 3072

    # --- MLflow (D9: servidor remoto propio, distinto del motor) ---
    mlflow_tracking_uri: str = ""

    # --- LangSmith observability ---
    langsmith_api_key: str = ""
    langsmith_tracing: bool = False
    langsmith_project: str = "fraud_evaluation_uni_tf"

    # --- Threat Intel ---
    threat_intel_offline: bool = False

settings = Settings()
