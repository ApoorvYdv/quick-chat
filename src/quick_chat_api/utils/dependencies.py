from fastapi import Header, HTTPException
from sqlalchemy import select

from quick_chat_api.core.constants.error_response import ErrorResponse
from quick_chat_api.core.database.connections import get_async_engine
from quick_chat_api.core.database.session_context_manager import session_context
from quick_chat_api.core.models.config.config import Agencies, Config
from quick_chat_api.utils.context import RequestContext

LOCALIZATION_SECTION = "localization"
TIMEZONE_KEY = "timezone"


async def validate_active_agency(agency: str) -> str | None:
    """Raise 404 for an unknown agency; return its configured timezone, if any."""
    engine = get_async_engine()
    async with session_context(engine) as session:
        stmt = select(Agencies).where(Agencies.name == agency)
        if await session.scalar(stmt) is None:
            raise HTTPException(status_code=404, detail=ErrorResponse.AGENCY_NOT_FOUND)
        timezone_stmt = select(Config.config_value).where(
            Config.agency_name == agency,
            Config.config_section == LOCALIZATION_SECTION,
            Config.config_key == TIMEZONE_KEY,
        )
        timezone = await session.scalar(timezone_stmt)
        return timezone if isinstance(timezone, str) else None


async def get_agency_header(agency: str = Header(...)):
    if not agency:
        raise HTTPException(status_code=400, detail=ErrorResponse.CLIENT_NOT_PROVIDED)

    RequestContext.timezone = await validate_active_agency(agency)
    RequestContext.agency = agency
    return agency
