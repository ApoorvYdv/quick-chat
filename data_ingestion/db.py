import os

from dotenv import load_dotenv
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

load_dotenv()


def build_db_url(async_driver: bool = False):
    driver: str
    if not async_driver:
        driver = "postgresql"
    else:
        driver = "postgresql+asyncpg"
    url_object = URL.create(
        drivername=driver,
        username=os.getenv("DB_USERNAME"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")) if os.getenv("DB_PORT") else None,
        database=os.getenv("DB_NAME"),
    )
    return url_object


DATABASE_URL = build_db_url(async_driver=True)
print(DATABASE_URL)

engine: AsyncEngine = create_async_engine(DATABASE_URL)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
