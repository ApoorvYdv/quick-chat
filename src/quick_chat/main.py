from fastapi import FastAPI
from fastapi.responses import RedirectResponse

app = FastAPI(
    title="Quick Chat",
    description="Quick Chat is a real-time messaging application",
    version="1.0.0",
    responses={404: {"description": "Not Found"}},
)


@app.get("/", include_in_schema=False)
def read_root():
    return RedirectResponse(url="/docs")
