from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from quick_chat_api.core.controllers import health_controller
from quick_chat_api.core.vectorstore.exceptions import VectorStoreOperationError
from quick_chat_api.main import app


def test_healthz_needs_no_dependencies() -> None:
    res = TestClient(app).get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_readyz_503_with_generic_body_when_vector_store_down() -> None:
    store = MagicMock()
    store.ping.side_effect = VectorStoreOperationError("secret detail")
    with (
        patch.object(
            health_controller.HealthController, "_check_postgres", return_value=True
        ),
        patch.object(health_controller, "get_vector_store", return_value=store),
    ):
        res = TestClient(app).get("/readyz")
    assert res.status_code == 503
    assert res.json() == {"status": "unavailable"}


def test_readyz_ok_when_dependencies_up() -> None:
    with (
        patch.object(
            health_controller.HealthController, "_check_postgres", return_value=True
        ),
        patch.object(health_controller, "get_vector_store", return_value=MagicMock()),
    ):
        res = TestClient(app).get("/readyz")
    assert res.status_code == 200


def test_unhandled_exception_returns_stable_shape() -> None:
    with patch.object(
        health_controller.HealthController, "is_ready", side_effect=RuntimeError("boom")
    ):
        res = TestClient(app, raise_server_exceptions=False).get("/readyz")
    assert res.status_code == 500
    assert res.json() == {"detail": "Internal server error."}
