from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from starlette_context import plugins
from starlette_context.middleware import RawContextMiddleware

from quick_chat_api.core.database.connections import get_async_engine
from quick_chat_api.routers.health_router import router as health_router
from quick_chat_api.routers.ingestion_router import router as ingestion_router
from quick_chat_api.utils.common.logger import logger

INTERNAL_ERROR_DETAIL = "Internal server error."


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await get_async_engine().dispose()


app = FastAPI(
    title="Quick Chat",
    description=(
        "Quick Chat — a grounded, multi-tenant RAG API for natural-language "
        "questions about court case data."
    ),
    version="1.0.0",
    responses={404: {"description": "Not Found"}},
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(ingestion_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unhandled exception",
        extra={"path": request.url.path, "error": type(exc).__name__},
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": INTERNAL_ERROR_DETAIL},
    )


@app.get("/", include_in_schema=False)
def read_root():
    return RedirectResponse(url="/docs")


app.add_middleware(
    RawContextMiddleware,
    plugins=[plugins.RequestIdPlugin(), plugins.CorrelationIdPlugin()],
)
