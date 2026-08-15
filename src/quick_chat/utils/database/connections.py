from sqlalchemy.ext.asyncio import create_async_engine

from quick_chat.settings.config import settings


class AsyncDatabaseSession:
    pool_size = settings.DB_POOL_SIZE
    max_overflow = settings.DB_MAX_OVERFLOW

    engine = create_async_engine(
        settings.DATABASE_URL,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_recycle=3600,  # Testing arguments might be removed if we see performance degradation
        pool_use_lifo=True,  # Testing arguments might be removed if we see performance degradation
        pool_pre_ping=True,  # Testing arguments might be removed if we see performance degradation
    )

    def __call__(self):
        return self.engine


get_async_engine = AsyncDatabaseSession()
