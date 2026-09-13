from fastapi import Header, HTTPException
from sqlalchemy import select

from quick_chat_api.core.constants.error_response import ErrorResponse
from quick_chat_api.core.database.connections import get_async_engine
from quick_chat_api.core.database.session_context_manager import session_context
from quick_chat_api.core.models.config.config import Agencies
from quick_chat_api.utils.context import RequestContext


async def validate_active_agency(agency: str):
    engine = get_async_engine()
    async with session_context(engine) as session:
        stmt = select(Agencies).where(Agencies.name == agency)
        agency = await session.scalar(stmt)
        if agency is None:
            raise HTTPException(status_code=404, detail=ErrorResponse.AGENCY_NOT_FOUND)


async def get_agency_header(agency: str = Header(...)):
    if not agency:
        raise HTTPException(status_code=400, detail=ErrorResponse.CLIENT_NOT_PROVIDED)

    await validate_active_agency(agency)
    RequestContext.agency = agency
    return agency
