from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from quick_chat_api.core.constants.error_response import ErrorResponse
from quick_chat_api.core.controllers import ingestion_controller as ic
from quick_chat_api.main import app
from quick_chat_api.modules.embedding.ingestion_service import (
    CaseIngestionResult,
    EntityIngestionOutcome,
    IngestionOutcomeKind,
)
from quick_chat_api.utils import dependencies as deps


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestAgencyHeader:
    def test_missing_header_is_rejected(self, client: TestClient) -> None:
        resp = client.post(f"/cases/{uuid4()}/index/reindex")
        assert resp.status_code == 422

    def test_empty_header_returns_unified_client_error(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resp = client.post(f"/cases/{uuid4()}/index/reindex", headers={"agency": ""})

        assert resp.status_code == 400
        assert resp.json()["detail"] == ErrorResponse.CLIENT_NOT_PROVIDED

    def test_unknown_agency_returns_unified_not_found_error(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            deps,
            "validate_active_agency",
            AsyncMock(
                side_effect=HTTPException(
                    status_code=404, detail=ErrorResponse.AGENCY_NOT_FOUND
                )
            ),
        )

        resp = client.post(
            f"/cases/{uuid4()}/index/reindex", headers={"agency": "unknown"}
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == ErrorResponse.AGENCY_NOT_FOUND


class TestReindexCase:
    def test_success_delegates_to_controller(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(deps, "validate_active_agency", AsyncMock())
        case_id = uuid4()

        async def fake_reindex_case(self, cid, *, force):
            assert cid == case_id
            assert force is False
            return CaseIngestionResult(
                case_id=cid,
                outcomes=[
                    EntityIngestionOutcome(
                        source_type="case",
                        source_id="1",
                        kind=IngestionOutcomeKind.EMBEDDED,
                        chunk_count=1,
                    )
                ],
            )

        monkeypatch.setattr(ic.IngestionController, "reindex_case", fake_reindex_case)

        resp = client.post(
            f"/cases/{case_id}/index/reindex", headers={"agency": "acme"}
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["embedded"] == 1
        assert body["failed"] == 0

    def test_case_not_found_returns_unified_error(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(deps, "validate_active_agency", AsyncMock())

        async def fake_reindex_case(self, cid, *, force):
            raise ic.CaseNotFoundControllerError(f"case_id={cid} not found")

        monkeypatch.setattr(ic.IngestionController, "reindex_case", fake_reindex_case)

        resp = client.post(
            f"/cases/{uuid4()}/index/reindex", headers={"agency": "acme"}
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == ErrorResponse.CASE_NOT_FOUND


class TestDeleteCaseIndex:
    def test_success_delegates_to_controller(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(deps, "validate_active_agency", AsyncMock())
        case_id = uuid4()

        async def fake_delete_case_index(self, cid):
            assert cid == case_id
            return 3

        monkeypatch.setattr(
            ic.IngestionController, "delete_case_index", fake_delete_case_index
        )

        resp = client.request(
            "DELETE", f"/cases/{case_id}/index", headers={"agency": "acme"}
        )

        assert resp.status_code == 200
        assert resp.json()["deleted_sources"] == 3
