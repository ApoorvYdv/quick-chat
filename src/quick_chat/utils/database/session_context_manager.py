import time
from contextlib import asynccontextmanager

from sqlalchemy import event, literal, or_, true
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session, with_loader_criteria

# WARNING: Do NOT remove this import!
# This import is required to register the @event.listens_for("after_flush")
# hook for the ROA (Register of Actions) audit trail system.
# Without it, automatic case history logging will silently fail.
from quick_chat.core.models.models import AgencyBase
from quick_chat.utils.common.logger import logger


def _register_query_timing(sync_engine) -> None:
    """
    Logs statement text + execution time for every query run through this
    engine. Idempotent — safe even if called multiple times on the same
    underlying sync engine (schema_translate_map creates a new proxy each
    call, but .sync_engine is stable, so this only attaches once).
    """
    if getattr(sync_engine, "_query_timing_registered", False):
        return
    sync_engine._query_timing_registered = True

    @event.listens_for(sync_engine, "before_cursor_execute")
    def _before_cursor_execute(
        conn, cursor, statement, parameters, context, executemany
    ):
        context._query_start_time = time.monotonic()

    @event.listens_for(sync_engine, "after_cursor_execute")
    def _after_cursor_execute(
        conn, cursor, statement, parameters, context, executemany
    ):
        duration_ms = (time.monotonic() - context._query_start_time) * 1000
        # Statement text only — never log `parameters`, bound params can
        # contain PII (emails, names, case numbers).
        logger.info(f"[db_query] duration_ms={duration_ms:.1f}")


@asynccontextmanager
async def session_context(engine: AsyncEngine, agency: str | None = None):
    schema_translate_map = {None: agency}
    option_engine = engine.execution_options(schema_translate_map=schema_translate_map)

    # _register_query_timing(option_engine.sync_engine)

    session = AsyncSession(option_engine, autoflush=False, expire_on_commit=False)

    session.info["schema_name"] = agency
    try:
        yield session
    except Exception as ex:
        await session.rollback()
        logger.error(f"An error occurred during a transaction: {ex}")
        raise

    finally:
        await session.close()


@event.listens_for(Session, "do_orm_execute")
def _add_is_active_filter(execute_state):
    """
    Filters all models with an `is_active` column to active-only rows,
    for top-level queries, joins, and relationship loads (lazy/selectin).

    Execution options:
    - include_inactive=True            -> disables filtering entirely
    - include_inactive_models=(A, B)   -> exempts only these models

    Relationship loads are skipped here since with_loader_criteria
    (propagate_to_loaders=True by default) already carries the rule
    forward automatically.

    Why the exemption is expressed in SQL rather than as a Python branch
    -------------------------------------------------------------------
    `with_loader_criteria` treats `_criteria` as a lambda statement: it is
    analyzed once and cached, and the compiled result lives in the engine's
    compiled cache, which is shared by every session and every agency schema.
    So `include_inactive_model_names` must not decide the *shape* of the
    criteria in Python — it has to reach the query as bound values, which is
    what `literal(cls.__name__).in_(...)` does. SQLAlchemy re-reads those
    values on every execution, so `track_closure_variables=False` (which keeps
    the tuple out of the lambda's cache key) stays safe.

    Rewriting the exemption as `if cls.__name__ in include_inactive_model_names:
    return true()` breaks that: the list stops reaching the query, and whichever
    request compiles the criteria first fixes the exemption for every request
    after it — silently, process-wide, across all agencies. Both directions of
    that failure are covered by tests/test_utils/test_is_active_filter.py.
    """

    if not execute_state.is_select or execute_state.is_relationship_load:
        return
    execution_options = execute_state.execution_options

    if execution_options.get("include_inactive", False):
        return

    include_inactive_model_names = tuple(
        m.__name__ for m in execution_options.get("include_inactive_models", ())
    )

    def _criteria(cls):
        if not hasattr(cls, "is_active"):
            return true()
        return or_(
            literal(cls.__name__).in_(include_inactive_model_names),
            cls.is_active.is_(True),
        )

    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            AgencyBase,
            _criteria,
            include_aliases=True,
            track_closure_variables=False,
        )
    )
