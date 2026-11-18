import os
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    APP_NAME: str = "AISD Incident Management System"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    # Security
    SECRET_KEY: str = "aisd-super-secret-key-for-local-demo-and-tests-2026"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://aisd_user:aisd_password@127.0.0.1:5432/aisd_db"

    # AI & Ollama Configuration
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"
    OLLAMA_EMBED_MODEL: str = "nomic-embed-text:latest"
    OLLAMA_TIMEOUT_SECONDS: int = 60
    AI_FALLBACK_TO_RULES: bool = True

    # Cloud AI
    CLOUD_AI_ENABLED: bool = False
    CLOUD_AI_PROVIDER: str = "none"
    CLOUD_AI_API_KEY: str = ""

    # Remediation
    REMEDIATION_MOCK_MODE: bool = False
    REQUIRE_APPROVAL_FOR_R2: bool = True
    REQUIRE_APPROVAL_FOR_R3: bool = True
    ALLOW_LOCAL_ENDPOINT_EXECUTION: bool = True

    # Agent
    CENTRAL_SERVER_URL: str = "http://127.0.0.1:8000"
    AGENT_HEARTBEAT_INTERVAL: int = 30
    AGENT_SYNC_INTERVAL: int = 15

    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

    model_config = SettingsConfigDict(
        env_file=(str(ROOT_ENV_FILE), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
