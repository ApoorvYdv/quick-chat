"""Liveness/readiness probes. Deliberately not tenant-scoped."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from quick_chat_api.core.controllers.health_controller import HealthController
from quick_chat_api.core.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/readyz", response_model=HealthResponse)
async def readyz(
    response: Response,
    controller: Annotated[HealthController, Depends()],
) -> HealthResponse:
    if await controller.is_ready():
        return HealthResponse(status="ok")
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="unavailable")
