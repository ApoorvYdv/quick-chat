"""The global `is_active` filter, including the include-inactive options.

Statements are compiled against the PostgreSQL dialect rather than executed,
so no database is needed: the filter is applied in `do_orm_execute`, and a
later listener captures the rewritten statement.
"""

import pytest
from sqlalchemy import event, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

import quick_chat_api.core.database.session_context_manager  # noqa: F401  (registers the listener)
from quick_chat_api.core.models.agency.agency import CaseRecord, Criminal


class _Captured(Exception):
    def __init__(self, sql: str, params: dict) -> None:
        self.sql = sql
        self.params = params

    @property
    def exempt_models(self) -> set[str]:
        """Model names that reached the query as the bound exemption list."""
        return {
            name
            for key, names in self.params.items()
            if key.startswith("include_inactive_model_names")
            for name in names
        }


@pytest.fixture(autouse=True)
def _capture_statement():
    def capture(execute_state):
        compiled = execute_state.statement.compile(dialect=postgresql.dialect())
        raise _Captured(str(compiled), compiled.params)

    event.listen(Session, "do_orm_execute", capture)
    yield
    event.remove(Session, "do_orm_execute", capture)


def _compile(stmt, **execution_options) -> _Captured:
    with pytest.raises(_Captured) as captured:
        Session().execute(stmt, execution_options=execution_options)
    return captured.value


def test_active_only_by_default() -> None:
    out = _compile(select(CaseRecord))
    assert "is_active IS true" in out.sql
    assert out.exempt_models == set()


def test_include_inactive_disables_filter() -> None:
    out = _compile(select(CaseRecord), include_inactive=True)
    assert "WHERE" not in out.sql


def test_exempt_model_reaches_the_query_as_bound_value() -> None:
    out = _compile(select(CaseRecord), include_inactive_models=(CaseRecord,))
    assert "is_active IS true" in out.sql
    assert out.exempt_models == {"CaseRecord"}


def test_exemption_does_not_leak_into_the_next_request() -> None:
    _compile(select(CaseRecord), include_inactive_models=(CaseRecord,))
    assert _compile(select(CaseRecord)).exempt_models == set()


def test_active_only_request_does_not_leak_into_exempt_request() -> None:
    _compile(select(CaseRecord))
    out = _compile(select(CaseRecord), include_inactive_models=(CaseRecord,))
    assert out.exempt_models == {"CaseRecord"}


def test_exemption_is_scoped_to_the_named_model() -> None:
    stmt = select(CaseRecord).join(Criminal, Criminal.case_record_id == CaseRecord.id)
    out = _compile(stmt, include_inactive_models=(Criminal,))
    assert out.exempt_models == {"Criminal"}
