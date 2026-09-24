"""A small client for Pangram's async AI-detection API.

Docs: https://docs.pangram.com/api-reference/ai-detection
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Self

import httpx

BASE_URL = "https://text.external-api.pangram.com"
DEFAULT_MODEL = "pangram-4"
TERMINAL_STAGES = frozenset({"STAGE_SUCCESS", "STAGE_FAILED"})

# Friendly explanations for the status codes Pangram documents.
STATUS_HINTS = {
    400: "Pangram couldn't parse the request.",
    401: "Your API key is missing or invalid.",
    402: "Your Pangram account is out of credits.",
    403: "This API key isn't allowed to use that model.",
    404: "Pangram couldn't find that task.",
    413: "That text is too large for a single request.",
    422: "Pangram rejected the text or model selector.",
    429: "You're being rate limited. Give it a moment and try again.",
    500: "Pangram hit an internal error.",
    503: "That model is temporarily unavailable.",
}

# Poll statuses worth retrying rather than giving up on.
_RETRYABLE = frozenset({429, 502, 503, 504})


class PangramError(Exception):
    """Anything that went wrong talking to Pangram, phrased for humans."""

    def __init__(self, message: str, *, status: int | None = None, detail: str | None = None):
        super().__init__(message)
        self.status = status
        self.detail = detail


@dataclass(frozen=True, slots=True)
class Window:
    """One independently classified segment of the analyzed text."""

    text: str
    label: str
    ai_assistance_score: float
    confidence: str
    start_index: int
    end_index: int
    word_count: int
    token_length: int | None = None
    is_humanized: bool | None = None
    humanizer_score: float | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Self:
        return cls(
            text=data.get("text", ""),
            label=data.get("label", ""),
            ai_assistance_score=float(data.get("ai_assistance_score") or 0.0),
            confidence=data.get("confidence", ""),
            start_index=int(data.get("start_index") or 0),
            end_index=int(data.get("end_index") or 0),
            word_count=int(data.get("word_count") or 0),
            token_length=data.get("token_length"),
            is_humanized=data.get("is_humanized"),
            humanizer_score=data.get("humanizer_score"),
        )


@dataclass(frozen=True, slots=True)
class Result:
    """A completed AI-detection result, plus the raw payload it came from."""

    text: str
    version: str
    headline: str
    prediction: str
    prediction_short: str
    fraction_ai: float
    fraction_ai_assisted: float
    fraction_human: float
    windows: tuple[Window, ...]
    dashboard_link: str | None
    raw: dict[str, Any]

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Self:
        return cls(
            text=data.get("text", ""),
            version=data.get("version", ""),
            headline=data.get("headline", ""),
            prediction=data.get("prediction", ""),
            prediction_short=data.get("prediction_short", ""),
            fraction_ai=float(data.get("fraction_ai") or 0.0),
            fraction_ai_assisted=float(data.get("fraction_ai_assisted") or 0.0),
            fraction_human=float(data.get("fraction_human") or 0.0),
            windows=tuple(Window.from_api(w) for w in data.get("windows") or ()),
            dashboard_link=data.get("dashboard_link") or None,
            raw=data,
        )

    @property
    def word_count(self) -> int:
        return sum(w.word_count for w in self.windows) or len(self.text.split())


class Pangram:
    """Thin synchronous wrapper around the task endpoints."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        timeout: float = 30.0,
        user_agent: str = "panc",
        transport: httpx.BaseTransport | None = None,
    ):
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={"x-api-key": api_key, "user-agent": user_agent},
            transport=transport,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def list_models(self) -> list[str]:
        return list(self._request("GET", "/models").get("models", []))

    def submit(self, text: str, *, model: str = DEFAULT_MODEL, dashboard_link: bool = False) -> str:
        body = {"text": text, "model": model, "public_dashboard_link": dashboard_link}
        return self._request("POST", "/task", json=body)["task_id"]

    def task(self, task_id: str) -> dict[str, Any]:
        return self._request("GET", f"/task/{task_id}")

    def detect(
        self,
        text: str,
        *,
        model: str = DEFAULT_MODEL,
        dashboard_link: bool = False,
        on_stage: Callable[[str], None] | None = None,
        timeout: float = 300.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> Result:
        """Submit `text` and poll until Pangram has a verdict."""
        task_id = self.submit(text, model=model, dashboard_link=dashboard_link)
        deadline = time.monotonic() + timeout
        delay = 0.4
        stage = ""
        while True:
            try:
                data = self.task(task_id)
            except PangramError as e:
                if e.status not in _RETRYABLE:
                    raise
                data = {"stage": stage}
            if data.get("stage") != stage:
                stage = data.get("stage", "")
                if on_stage:
                    on_stage(stage)
            if stage == "STAGE_SUCCESS":
                return Result.from_api(data)
            if stage == "STAGE_FAILED":
                # Failures carry their reason in the headline, e.g.
                # "preprocessing: Input text contains no valid text after preprocessing".
                raise PangramError(
                    "Pangram couldn't analyze that text.", detail=data.get("headline") or None
                )
            if time.monotonic() > deadline:
                raise PangramError(
                    f"Gave up waiting after {timeout:.0f}s.", detail=f"Task {task_id} is {stage}."
                )
            sleep(delay)
            delay = min(delay * 1.5, 2.0)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.TimeoutException as e:
            raise PangramError("Pangram took too long to respond.", detail=str(e) or None) from e
        except httpx.TransportError as e:
            raise PangramError("Couldn't reach Pangram.", detail=str(e) or None) from e

        if response.is_success:
            return response.json()

        status = response.status_code
        message = STATUS_HINTS.get(status, f"Pangram returned HTTP {status}.")
        raise PangramError(message, status=status, detail=_error_detail(response))


def _error_detail(response: httpx.Response) -> str | None:
    """Dig a human-readable reason out of an error response, if there is one."""
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()[:300] or None
    if not isinstance(body, dict):
        return str(body)[:300]
    detail = body.get("detail") or body.get("message") or body.get("error")
    if isinstance(detail, list):  # FastAPI-style validation errors
        detail = "; ".join(d.get("msg", str(d)) if isinstance(d, dict) else str(d) for d in detail)
    return str(detail)[:300] if detail else None
