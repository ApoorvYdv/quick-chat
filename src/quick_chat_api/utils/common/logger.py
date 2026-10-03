"""JSON logging over stdlib.

`logger` stays a plain stdlib logger (so `extra=` keeps working); structlog
only formats the records. `request_id`, `correlation_id` and `agency` are read
from the per-request context at log time, so they are present even when the
agency is resolved after the request starts.
"""

import logging
from typing import Any

import structlog
from starlette_context import context, plugins
from structlog.types import EventDict, Processor

from quick_chat_api.settings.config import settings

LOGGER_NAME = "api"

# Case content must never reach logs (CLAUDE.md §20).
SENSITIVE_KEYS = frozenset({"question", "prompt", "context", "answer", "content"})


def _add_request_context(_: Any, __: str, event_dict: EventDict) -> EventDict:
    if context.exists():
        event_dict.setdefault("request_id", context.get(plugins.RequestIdPlugin.key))
        event_dict.setdefault(
            "correlation_id", context.get(plugins.CorrelationIdPlugin.key)
        )
        if agency := context.get("agency"):
            event_dict.setdefault("agency", agency)
    return event_dict


def _drop_sensitive(_: Any, __: str, event_dict: EventDict) -> EventDict:
    for key in SENSITIVE_KEYS & event_dict.keys():
        del event_dict[key]
    return event_dict


def build_formatter() -> structlog.stdlib.ProcessorFormatter:
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.stdlib.ExtraAdder(),
        _add_request_context,
        _drop_sensitive,
    ]
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
    )


def configure_logging() -> None:
    log = logging.getLogger(LOGGER_NAME)
    if log.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(build_formatter())
    log.addHandler(handler)
    log.setLevel(settings.LOG_LEVEL.upper())
    log.propagate = False


configure_logging()
logger = logging.getLogger(LOGGER_NAME)
