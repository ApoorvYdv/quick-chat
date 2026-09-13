from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings from environment variables."""

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
        description="Embedding provider to use: 'local' (sentence-transformers) or 'openai'",
    )
    EMBEDDING_MODEL: str = Field(
        default="sentence-transformers/all-mpnet-base-v2",
        description="Embedding model identifier for the selected provider",
    )
    EMBEDDING_DIM: int = Field(
        default=768,
        description="Output dimensionality of the configured embedding model; "
        "must match the pgvector column width in ai_knowledge_chunk",
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
    EMBEDDING_VERSION: str = Field(
        default="v1",
        description="Embedding provider/model version, stamped into every chunk's "
        "embedding_version column and into the source's indexing key so a model "
        "or provider change is detected and triggers re-embedding",
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
    return Settings()


# Convenience instance
settings = get_settings()
