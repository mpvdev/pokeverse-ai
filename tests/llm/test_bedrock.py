from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from botocore.exceptions import EndpointConnectionError, NoCredentialsError
from botocore.stub import Stubber

from pokeverse.llm import (
    BedrockChat,
    LlmAuthError,
    LlmRequestError,
    LlmSettings,
    LlmUnavailableError,
)

SETTINGS = LlmSettings(model_id="test-model", region="us-east-1", temperature=0.3, max_tokens=64)


def converse_response(text: str = "Pikachu is Electric-type.") -> dict[str, Any]:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 12, "outputTokens": 7, "totalTokens": 19},
        "metrics": {"latencyMs": 100},
    }


def expected_request(
    prompt: str = "What type is Pikachu?",
    *,
    system: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 64,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "modelId": "test-model",
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"temperature": temperature, "maxTokens": max_tokens},
    }
    if system is not None:
        request["system"] = [{"text": system}]
    return request


@pytest.fixture
def stubbed() -> Iterator[tuple[BedrockChat, Stubber]]:
    client = boto3.client(
        "bedrock-runtime",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    with Stubber(client) as stubber:
        yield BedrockChat(SETTINGS, client=client), stubber
        stubber.assert_no_pending_responses()


def test_complete_returns_text_and_usage(stubbed: tuple[BedrockChat, Stubber]) -> None:
    chat, stubber = stubbed
    stubber.add_response("converse", converse_response(), expected_request())

    completion = chat.complete("What type is Pikachu?")

    assert completion.text == "Pikachu is Electric-type."
    assert completion.model_id == "test-model"
    assert completion.stop_reason == "end_turn"
    assert (completion.input_tokens, completion.output_tokens) == (12, 7)
    assert completion.total_tokens == 19
    assert completion.latency_ms >= 0


def test_system_prompt_and_overrides_are_sent(stubbed: tuple[BedrockChat, Stubber]) -> None:
    chat, stubber = stubbed
    stubber.add_response(
        "converse",
        converse_response(),
        expected_request(system="Be brief.", temperature=0.0, max_tokens=10),
    )

    chat.complete("What type is Pikachu?", system="Be brief.", temperature=0.0, max_tokens=10)


def test_multiple_text_blocks_are_joined(stubbed: tuple[BedrockChat, Stubber]) -> None:
    chat, stubber = stubbed
    response = converse_response()
    response["output"]["message"]["content"] = [{"text": "Hello, "}, {"text": "trainer!"}]
    stubber.add_response("converse", response, expected_request())

    assert chat.complete("What type is Pikachu?").text == "Hello, trainer!"


@pytest.mark.parametrize("prompt", ["", "   "])
def test_empty_prompt_is_rejected(stubbed: tuple[BedrockChat, Stubber], prompt: str) -> None:
    chat, _ = stubbed

    with pytest.raises(ValueError):
        chat.complete(prompt)


@pytest.mark.parametrize(
    ("code", "error"),
    [
        ("AccessDeniedException", LlmAuthError),
        ("UnrecognizedClientException", LlmAuthError),
        ("ExpiredTokenException", LlmAuthError),
        ("ThrottlingException", LlmUnavailableError),
        ("ServiceUnavailableException", LlmUnavailableError),
        ("InternalServerException", LlmUnavailableError),
        ("ModelTimeoutException", LlmUnavailableError),
        ("ValidationException", LlmRequestError),
        ("ResourceNotFoundException", LlmRequestError),
    ],
)
def test_client_errors_are_mapped(
    stubbed: tuple[BedrockChat, Stubber], code: str, error: type[Exception]
) -> None:
    chat, stubber = stubbed
    stubber.add_client_error("converse", service_error_code=code, service_message="boom")

    with pytest.raises(error, match=code):
        chat.complete("What type is Pikachu?")


class RaisingClient:
    def __init__(self, exception: Exception) -> None:
        self.exception = exception

    def converse(self, **_: Any) -> dict[str, Any]:
        raise self.exception


@pytest.mark.parametrize(
    ("exception", "error"),
    [
        (NoCredentialsError(), LlmAuthError),
        (EndpointConnectionError(endpoint_url="https://bedrock"), LlmUnavailableError),
    ],
)
def test_botocore_errors_are_mapped(exception: Exception, error: type[Exception]) -> None:
    chat = BedrockChat(SETTINGS, client=RaisingClient(exception))

    with pytest.raises(error):
        chat.complete("hi")


class StaticClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response

    def converse(self, **_: Any) -> dict[str, Any]:
        return self.response


def test_malformed_response_raises_request_error() -> None:
    chat = BedrockChat(SETTINGS, client=StaticClient({"output": {}}))

    with pytest.raises(LlmRequestError, match="Malformed"):
        chat.complete("hi")


@pytest.mark.bedrock
def test_live_bedrock_completion() -> None:
    completion = BedrockChat(LlmSettings.from_env()).complete(
        "Reply with exactly the word: pong", temperature=0.0, max_tokens=10
    )

    assert "pong" in completion.text.lower()
    assert completion.input_tokens > 0
    assert completion.output_tokens > 0
