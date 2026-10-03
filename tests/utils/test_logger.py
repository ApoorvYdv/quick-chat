import io
import json
import logging

from starlette_context import request_cycle_context

from quick_chat_api.utils.common.logger import build_formatter


def _emit(**extra) -> dict:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(build_formatter())
    log = logging.getLogger("api.test")
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        log.info("hello", extra=extra)
    finally:
        log.removeHandler(handler)
    return json.loads(stream.getvalue())


def test_emits_json_with_extra_and_drops_sensitive_keys() -> None:
    out = _emit(case_id="c1", content="secret", prompt="secret", answer="secret")
    assert out["event"] == "hello"
    assert out["case_id"] == "c1"
    assert out["level"] == "info"
    assert not {"content", "prompt", "answer"} & out.keys()


def test_adds_request_context_when_present() -> None:
    data = {"X-Request-ID": "r1", "X-Correlation-ID": "k1", "agency": "acme"}
    with request_cycle_context(data):
        out = _emit()
    assert (out["request_id"], out["correlation_id"], out["agency"]) == (
        "r1",
        "k1",
        "acme",
    )


def test_no_request_context_outside_a_request() -> None:
    assert "request_id" not in _emit()
