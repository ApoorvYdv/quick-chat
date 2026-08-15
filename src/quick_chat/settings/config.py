from functools import lru_cache

from pydantic import Field, field_validator
from pydantic.v1 import BaseSettings


class Settings(BaseSettings):
    """Application settings from environment variables."""

    # Database
    DATABASE_URL: str = Field(description="Database connection URL", required=True)
    DB_POOL_SIZE: int = Field(
        default=5, description="Database connection pool size", ge=1
    )
    DB_MAX_OVERFLOW: int = Field(
        default=10, description="Database max overflow connections", ge=0
    )

    # AWS S3
    AWS_S3_BUCKET: str = Field(description="AWS S3 bucket name", required=True)

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Ensure database URL is not empty."""
        if not v or v.strip() == "":
            raise ValueError("DATABASE_URL cannot be empty")
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Singleton instance with caching
@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Convenience instance
settings = get_settings()
