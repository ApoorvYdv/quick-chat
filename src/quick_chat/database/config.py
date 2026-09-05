from sqlalchemy import URL

from quick_chat.settings.config import settings


class DatabaseConfig:
    db_username: str | None
    db_password: str | None
    db_engine: str
    db_host: str | None
    db_port: str | None
    db_name: str | None

    def __init__(self) -> None:
        self.db_username = settings.DB_USERNAME
        self.db_password = settings.DB_PASSWORD
        self.db_engine = settings.DB_ENGINE
        self.db_host = settings.DB_HOST
        self.db_port = settings.DB_PORT
        self.db_name = settings.DB_NAME

        if self.db_engine == "postgres":
            # Handle default engine string from SSM
            self.db_engine = "postgresql"

    def build_db_url(self, async_driver: bool = False) -> URL:
        driver: str
        if not async_driver:
            driver = self.db_engine
        else:
            driver = "postgresql+asyncpg"
        url_object = URL.create(
            drivername=driver,
            username=self.db_username,
            password=self.db_password,
            host=self.db_host,
            port=int(self.db_port) if self.db_port else None,
            database=self.db_name,
        )
        return url_object

    def build_url_as_string(self) -> str:
        return self.build_db_url().render_as_string(hide_password=False)
