from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings from environment variables."""

    # Logging
    LOG_LEVEL: str = Field(default="INFO", description="Application log level")

    DEFAULT_TIMEZONE: str = Field(
        default="America/Denver",
        description="IANA timezone used when an agency has no localization.timezone config",
    )

    # Database
    DB_USERNAME: str = Field(description="Database username")
    DB_PASSWORD: str = Field(description="Database password")
    DB_HOST: str = Field(description="Database host")
    DB_PORT: str = Field(description="Database port")
    DB_NAME: str = Field(description="Database name")
    DB_POOL_SIZE: int = Field(
        default=5, description="Database connection pool size", ge=1
    )
    DB_MAX_OVERFLOW: int = Field(
        default=10, description="Database max overflow connections", ge=0
    )

    # AWS S3
    AWS_S3_BUCKET: str = Field(description="AWS S3 bucket name")

    # Embeddings
    EMBEDDING_PROVIDER: str = Field(
        default="local",
        description="Embedding provider to use: 'local' (sentence-transformers) or 'remote' (inference service)",
    )
    EMBEDDING_MODEL: str = Field(
        default="sentence-transformers/all-mpnet-base-v2",
        description="Embedding model identifier for the selected provider",
    )
    EMBEDDING_DIM: int = Field(
        default=768,
        description="Output dimensionality of the configured embedding model; "
        "must match the vector store collection dimension",
        gt=0,
    )
    EMBEDDING_BATCH_SIZE: int = Field(
        default=32, description="Number of texts embedded per batch call", ge=1
    )
    EMBEDDING_DEVICE: str = Field(
        default="cpu",
        description="Device for local embedding inference: 'cpu', 'mps', or 'cuda'",
    )
    EMBEDDING_API_KEY: str | None = Field(
        default=None, description="API key for a remote embedding provider (if any)"
    )
    EMBEDDING_REMOTE_URL: str = Field(
        default="http://inference:8001",
        description="Base URL of the inference service, used when EMBEDDING_PROVIDER=remote",
    )
    EMBEDDING_REMOTE_TIMEOUT_S: float = Field(
        default=30.0, description="Timeout for inference service calls", gt=0
    )
    EMBEDDING_VERSION: str = Field(
        default="v1",
        description="Embedding provider/model version, stamped into every chunk's "
        "embedding_version column and into the source's indexing key so a model "
        "or provider change is detected and triggers re-embedding",
    )

    # Vector store
    VECTOR_STORE_PROVIDER: str = Field(
        default="qdrant",
        description="Vector store provider to use: 'qdrant'",
    )
    QDRANT_URL: str = Field(
        default="http://localhost:6333",
        description="Qdrant base URL",
    )
    QDRANT_API_KEY: str | None = Field(
        default=None, description="Qdrant API key (unset for local/self-hosted)"
    )
    QDRANT_COLLECTION_PREFIX: str = Field(
        default="case_knowledge_chunks",
        description="Prefix for per-agency Qdrant collections (collection-per-tenant: "
        "each agency gets its own collection named '<prefix>__<agency>'), so vectors "
        "are physically isolated per tenant rather than only payload-filtered",
    )

    # Chunking
    CHUNKING_STRATEGY: str = Field(
        default="structured",
        description="Chunking strategy to use: 'structured' (field-boundary-aware, "
        "for projected structured documents)",
    )
    CHUNKING_VERSION: str = Field(
        default="v1",
        description="Chunking strategy version, stamped into each chunk's metadata "
        "so re-chunking with a changed strategy can be detected",
    )
    CHUNK_TOKEN_SAFETY_MARGIN: float = Field(
        default=0.9,
        description="Fraction of the embedding provider's max_tokens usable per "
        "chunk, leaving headroom for tokenizer special tokens",
        gt=0,
        le=1,
    )
    CHUNK_OVERLAP_RATIO: float = Field(
        default=0.15,
        description="Fraction of a token-window slice to overlap with the next "
        "slice when a single field's text alone exceeds the chunk token budget",
        ge=0,
        lt=1,
    )

    # LLM (local Ollama by default)
    LLM_PROVIDER: str = Field(
        default="ollama", description="Chat model provider: 'ollama'"
    )
    LLM_BASE_URL: str = Field(
        default="http://localhost:11434", description="Ollama server base URL"
    )
    LLM_ANSWER_MODEL: str = Field(
        default="qwen3:4b", description="Model for the 'answer' role"
    )
    LLM_ROUTER_MODEL: str = Field(
        default="qwen3:4b", description="Model for the 'router' (understand) role"
    )
    LLM_TIMEOUT_S: float = Field(
        default=120.0, description="Per-call LLM timeout in seconds", gt=0
    )
    LLM_MAX_TOKENS: int = Field(
        default=1024, description="Max tokens generated per LLM call", ge=1
    )
    LLM_TEMPERATURE: float = Field(
        default=0.0, description="Sampling temperature (0 for grounded answers)", ge=0
    )

    # LangSmith (redacted metadata-only tracing; off unless enabled per environment)
    LANGSMITH_ENABLED: bool = Field(
        default=False, description="Send redacted per-node traces to LangSmith"
    )
    LANGSMITH_API_KEY: SecretStr | None = Field(default=None)
    LANGSMITH_PROJECT: str = Field(default="quick-chat")

    # Chat pipeline
    CONTEXT_MAX_TOKENS: int = Field(
        default=12000, description="Token budget for evidence sent to the LLM", ge=1
    )
    CHAT_HISTORY_MAX_TURNS: int = Field(
        default=6, description="Conversation turns kept in the prompt", ge=0
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


# Singleton instance with caching
@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()  # type: ignore[call-arg]  # fields come from the environment


# Convenience instance
settings = get_settings()
