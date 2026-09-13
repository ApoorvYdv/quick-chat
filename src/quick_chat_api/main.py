from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from starlette_context import plugins
from starlette_context.middleware import RawContextMiddleware

from quick_chat_api.routers.ingestion_router import router as ingestion_router

app = FastAPI(
    title="Quick Chat",
    description="Quick Chat is a real-time messaging application",
    version="1.0.0",
    responses={404: {"description": "Not Found"}},
)

app.include_router(ingestion_router)


@app.get("/", include_in_schema=False)
def read_root():
    return RedirectResponse(url="/docs")


app.add_middleware(
    RawContextMiddleware,
    plugins=[plugins.RequestIdPlugin(), plugins.CorrelationIdPlugin()],
)
