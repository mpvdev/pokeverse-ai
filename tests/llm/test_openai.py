from types import SimpleNamespace
from typing import Any

import httpx2
import pytest
from dotenv import find_dotenv, load_dotenv
from openai import APIConnectionError, AuthenticationError, BadRequestError, RateLimitError

from pokeverse.llm import (
    LlmAuthError,
    LlmRequestError,
    LlmSettings,
    LlmUnavailableError,
    OpenAIChat,
)

SETTINGS = LlmSettings(model_id="test-model", temperature=0.3, max_tokens=64)


def openai_response(text: str = "Pikachu is Electric-type.") -> SimpleNamespace:
    return SimpleNamespace(
        output_text=text,
        model="test-model",
        status="completed",
        usage=SimpleNamespace(input_tokens=12, output_tokens=7),
    )


class FakeResponses:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.requests: list[dict[str, Any]] = []

    def create(self, **request: Any) -> Any:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.responses = FakeResponses(response, error)


def test_complete_returns_text_and_usage() -> None:
    client = FakeClient(openai_response())
    chat = OpenAIChat(SETTINGS, client=client)

    completion = chat.complete("What type is Pikachu?")

    assert completion.text == "Pikachu is Electric-type."
    assert completion.model_id == "test-model"
    assert completion.stop_reason == "completed"
    assert (completion.input_tokens, completion.output_tokens) == (12, 7)
    assert completion.total_tokens == 19
    assert completion.latency_ms >= 0
    assert client.responses.requests == [
        {
            "model": "test-model",
            "input": "What type is Pikachu?",
            "temperature": 0.3,
            "max_output_tokens": 64,
            "reasoning": {"effort": "none"},
        }
    ]


def test_reasoning_effort_omits_temperature() -> None:
    client = FakeClient(openai_response())
    settings = LlmSettings(model_id="test-model", reasoning_effort="low")
    chat = OpenAIChat(settings, client=client)

    chat.complete("What type is Pikachu?", temperature=0.9)

    request = client.responses.requests[0]
    assert request["reasoning"] == {"effort": "low"}
    assert "temperature" not in request


def test_system_prompt_and_overrides_are_sent() -> None:
    client = FakeClient(openai_response())
    chat = OpenAIChat(SETTINGS, client=client)

    chat.complete("What type is Pikachu?", system="Be brief.", temperature=0.0, max_tokens=10)

    assert client.responses.requests[0] == {
        "model": "test-model",
        "input": "What type is Pikachu?",
        "instructions": "Be brief.",
        "temperature": 0.0,
        "max_output_tokens": 10,
        "reasoning": {"effort": "none"},
    }


@pytest.mark.parametrize("prompt", ["", "   "])
def test_empty_prompt_is_rejected(prompt: str) -> None:
    chat = OpenAIChat(SETTINGS, client=FakeClient(openai_response()))

    with pytest.raises(ValueError):
        chat.complete(prompt)


def api_error(error_type: type[Exception], status_code: int) -> Exception:
    request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
    if error_type is APIConnectionError:
        return APIConnectionError(request=request)
    response = httpx2.Response(status_code, request=request)
    return error_type("boom", response=response, body=None)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("exception", "error"),
    [
        (api_error(AuthenticationError, 401), LlmAuthError),
        (api_error(RateLimitError, 429), LlmUnavailableError),
        (api_error(APIConnectionError, 0), LlmUnavailableError),
        (api_error(BadRequestError, 400), LlmRequestError),
    ],
)
def test_openai_errors_are_mapped(exception: Exception, error: type[Exception]) -> None:
    chat = OpenAIChat(SETTINGS, client=FakeClient(error=exception))

    with pytest.raises(error, match="boom|Connection error"):
        chat.complete("What type is Pikachu?")


def test_missing_api_key_raises_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(LlmAuthError, match="OPENAI_API_KEY"):
        OpenAIChat(SETTINGS)


def test_malformed_response_raises_request_error() -> None:
    chat = OpenAIChat(SETTINGS, client=FakeClient(SimpleNamespace(output_text="hello")))

    with pytest.raises(LlmRequestError, match="Malformed"):
        chat.complete("hi")


@pytest.mark.openai
def test_live_openai_completion() -> None:
    load_dotenv(find_dotenv(usecwd=True))
    completion = OpenAIChat(LlmSettings.from_env()).complete(
        "Reply with exactly the word: pong", temperature=0.0, max_tokens=16
    )

    assert "pong" in completion.text.lower()
    assert completion.input_tokens > 0
    assert completion.output_tokens > 0
