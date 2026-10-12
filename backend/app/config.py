from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore", hide_input_in_errors=True)
    database_url: str = "postgresql+psycopg://campus:campus@localhost:5432/campus"
    redis_url: str = "redis://localhost:6379/0"
    storage_dir: Path = Path("./data/files")
    model_mode: str = "mock"
    llm_api_base: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_api_style: Literal["openai", "deepseek"] = "openai"
    llm_thinking_enabled: bool = False
    llm_reasoning_effort: Literal["", "none", "minimal", "low", "medium", "high", "xhigh", "max"] = ""
    llm_max_completion_tokens: int | None = Field(default=None, gt=0)
    embedding_api_base: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_revision: str = ""
    embedding_requires_api_key: bool = True
    embedding_dimensions: int = 1024
    embedding_send_dimensions: bool = True
    provider_timeout: float = Field(default=30, gt=0, le=180)
    retrieval_mode: str = "hybrid"
    public_origin: str = "http://localhost:8080"
    cookie_secure: bool = False
    max_upload_bytes: int = 20 * 1024 * 1024
    max_pdf_pages: int = 100
    chunk_size: int = 1200
    chunk_overlap: int = 120
    chunk_min_chars: int = 300
    chunk_policy: str = "semantic-v2"
    material_max_tokens: int = 8192
    retrieval_top_k: int = 6
    max_context_chars: int = 8000
    job_timeout_seconds: int = 600
    demo_student_password: str = ""
    demo_admin_password: str = ""

    @model_validator(mode="after")
    def validate_configuration(self):
        if self.model_mode not in {"mock", "real"}:
            raise ValueError("MODEL_MODE must be mock or real")
        if self.embedding_dimensions != 1024:
            raise ValueError("This schema requires 1024-dimensional vectors")
        if self.retrieval_mode not in {"hybrid", "vector"}:
            raise ValueError("RETRIEVAL_MODE must be hybrid or vector")
        if not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        if not 0 < self.chunk_min_chars <= self.chunk_size or not 1 <= self.retrieval_top_k <= 20:
            raise ValueError("Invalid semantic chunk or retrieval configuration")
        if self.max_context_chars < 1000:
            raise ValueError("MAX_CONTEXT_CHARS must be at least 1000")
        if self.model_mode == "real":
            fields = (
                "llm_api_base",
                "llm_api_key",
                "llm_model",
                "embedding_api_base",
                "embedding_model",
            )
            if self.embedding_requires_api_key:
                fields += ("embedding_api_key",)
            if any(not getattr(self, name).strip() for name in fields):
                raise ValueError(
                    "Real mode requires both chat and embedding endpoint/model/key configuration"
                )
            for base in (self.llm_api_base, self.embedding_api_base):
                url = urlsplit(base)
                if url.scheme not in {"http", "https"} or not url.hostname:
                    raise ValueError("Model API bases must be HTTP(S) URLs")
                if url.username or url.password or url.query or url.fragment:
                    raise ValueError("Model API bases cannot contain credentials, query strings or fragments")
        if self.llm_model.startswith("gpt-6.1-sol") and self.llm_reasoning_effort in {"none", "minimal"}:
            raise ValueError("gpt-6.1-sol requires reasoning effort low or higher")
        if (
            self.llm_api_style == "deepseek"
            and self.llm_thinking_enabled
            and self.llm_reasoning_effort == "none"
        ):
            raise ValueError("DeepSeek thinking enabled conflicts with reasoning effort none")
        return self

    @property
    def chunk_policy_key(self):
        return f"{self.chunk_policy}:{self.chunk_size}:{self.chunk_overlap}:{self.chunk_min_chars}"

    @property
    def index_key(self):
        import hashlib

        identity = (
            "mock-hash-v1"
            if self.model_mode == "mock"
            else f"{self.embedding_api_base}|{self.embedding_model}"
        )
        if self.model_mode == "real" and self.embedding_revision:
            identity += f"|{self.embedding_revision}"
        return f"{self.model_mode}:{hashlib.sha256(identity.encode()).hexdigest()[:24]}:1024"


@lru_cache
def settings():
    return Settings()
