from typing import Literal

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    POSTGRES_HOST: str
    POSTGRES_PORT: int
    POSTGRES_DB: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str

    WORKFLOW_DB_SCHEMA: str
    CASE_DATA_DB_SCHEMA: str

    TEMPORAL_ADDRESS: str = "temporal:7233"
    TEMPORAL_TASK_QUEUE: str = "case-workflow-task-queue"

    MINIO_ROOT_USER: str
    MINIO_ROOT_PASSWORD: str
    MINIO_ENDPOINT: str
    MINIO_BUCKET: str = "case-documents"
    MINIO_SECURE: bool = False

    AUTH_URL: str
    AUTH_CLIENT_ID: str = "api_physical"
    AUTH_CLIENT_SECRET: str

    # Shared with the gateway, which sends it on every request (X-Internal-
    # Secret). Requests without it are refused, so only the gateway can call
    # this API and vouch for the user (X-User-Id). Unset: every request is
    # refused. Also sent on risk framework calls (made by the worker).
    INTERNAL_API_SECRET: str | None = None

    #todo fix this
    # JSON-LD export (app/semantic): IRIs are https://ontology.<env>.biofindashboard.eu/...
    SEMANTIC_ENV: Literal["dev", "prd"] = "dev"

    RISK_URL: str = "https://api.dev.biofindashboard.eu/api/vulnerability/"
    # Priority calculations can take a long time when the framework has no
    # cached result for a polygon yet.
    RISK_TIMEOUT_SECONDS: float = 30 * 60

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def sync_database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

settings = Settings()