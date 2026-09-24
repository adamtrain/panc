import json

import httpx
import pytest

from panc.client import Pangram, PangramError


def client_for(handler) -> Pangram:
    return Pangram("secret", transport=httpx.MockTransport(handler))


def test_detect_submits_then_polls_until_success(mixed):
    seen = []
    polls = iter([{"task_id": "t1", "stage": "STAGE_PREPROCESSING"}, mixed])

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"task_id": "t1"})
        return httpx.Response(200, json=next(polls))

    stages = []
    result = client_for(handler).detect(
        "some text", model="pangram-4", on_stage=stages.append, sleep=lambda _: None
    )

    submit, *gets = seen
    assert submit.url.path == "/task"
    assert submit.headers["x-api-key"] == "secret"
    assert json.loads(submit.content) == {
        "text": "some text",
        "model": "pangram-4",
        "public_dashboard_link": False,
    }
    assert [g.url.path for g in gets] == ["/task/t1", "/task/t1"]
    assert stages == ["STAGE_PREPROCESSING", "STAGE_SUCCESS"]
    assert result.prediction_short == "Mixed"
    assert len(result.windows) == 4
    assert result.windows[2].is_humanized is True


def test_failed_stage_raises_with_headline():
    failed = {"stage": "STAGE_FAILED", "headline": "preprocessing: no valid text"}

    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"task_id": "t1"})
        return httpx.Response(200, json=failed)

    with pytest.raises(PangramError) as e:
        client_for(handler).detect("x", sleep=lambda _: None)
    assert e.value.detail == "preprocessing: no valid text"


def test_http_errors_become_friendly_messages():
    def handler(request):
        return httpx.Response(401, json={"detail": "Invalid API key"})

    with pytest.raises(PangramError) as e:
        client_for(handler).submit("x")
    assert e.value.status == 401
    assert "API key" in str(e.value)
    assert e.value.detail == "Invalid API key"


def test_rate_limited_polls_are_retried(docs_example):
    responses = iter(
        [httpx.Response(429, json={"detail": "slow down"}), httpx.Response(200, json=docs_example)]
    )

    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"task_id": "t1"})
        return next(responses)

    result = client_for(handler).detect("x", sleep=lambda _: None)
    assert result.headline == "AI Assisted"


def test_list_models():
    def handler(request):
        assert request.url.path == "/models"
        return httpx.Response(200, json={"models": ["default", "pangram-4"]})

    assert client_for(handler).list_models() == ["default", "pangram-4"]
