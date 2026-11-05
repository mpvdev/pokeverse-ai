"""Minimal Amazon Bedrock chat client built on the Converse API.

The Converse API is model-agnostic: the same request shape works for Amazon
Nova, Anthropic Claude, Meta Llama, etc., and it natively supports tool calling,
which later steps build on.
"""

import time
from dataclasses import dataclass, replace
from typing import Any

import boto3
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
    ReadTimeoutError,
    TokenRetrievalError,
    UnauthorizedSSOTokenError,
)

from pokeverse.llm.config import LlmSettings

_AUTH_ERROR_CODES = {
    "AccessDeniedException",
    "UnrecognizedClientException",
    "ExpiredTokenException",
}
_UNAVAILABLE_ERROR_CODES = {
    "ThrottlingException",
    "ServiceUnavailableException",
    "InternalServerException",
    "ModelNotReadyException",
    "ModelTimeoutException",
}


class LlmError(Exception):
    """Base class for LLM inference errors."""


class LlmAuthError(LlmError):
    """Missing/expired credentials or no access to the model."""


class LlmUnavailableError(LlmError):
    """Transient failure: throttling, service outage, timeouts, network."""


class LlmRequestError(LlmError):
    """The request was rejected (bad model id, invalid parameters) or the reply was malformed."""


@dataclass(frozen=True, slots=True)
class Completion:
    """A model reply plus the metadata needed to reason about cost and latency."""

    text: str
    model_id: str
    stop_reason: str
    input_tokens: int
    output_tokens: int
    latency_ms: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class BedrockChat:
    """Single-turn text completion via ``bedrock-runtime`` ``converse``.

    Pass ``client`` to inject a preconfigured or stubbed boto3 client (tests).
    """

    def __init__(self, settings: LlmSettings | None = None, client: Any | None = None) -> None:
        self.settings = settings or LlmSettings.from_env()
        self._client = client or boto3.client("bedrock-runtime", region_name=self.settings.region)

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Completion:
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        settings = replace(
            self.settings,
            temperature=self.settings.temperature if temperature is None else temperature,
            max_tokens=self.settings.max_tokens if max_tokens is None else max_tokens,
        )

        request: dict[str, Any] = {
            "modelId": settings.model_id,
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {
                "temperature": settings.temperature,
                "maxTokens": settings.max_tokens,
            },
        }
        if system:
            request["system"] = [{"text": system}]

        started = time.perf_counter()
        response = self._call(request)
        latency_ms = round((time.perf_counter() - started) * 1000)
        return _parse_response(response, settings.model_id, latency_ms)

    def _call(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._client.converse(**request)
        except (NoCredentialsError, TokenRetrievalError, UnauthorizedSSOTokenError) as error:
            raise LlmAuthError(
                f"AWS credentials unavailable or expired ({error}). Try: aws sso login"
            ) from error
        except (EndpointConnectionError, ReadTimeoutError) as error:
            raise LlmUnavailableError(f"Could not reach Bedrock: {error}") from error
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            message = error.response.get("Error", {}).get("Message", str(error))
            if code in _AUTH_ERROR_CODES:
                raise LlmAuthError(f"{code}: {message}") from error
            if code in _UNAVAILABLE_ERROR_CODES:
                raise LlmUnavailableError(f"{code}: {message}") from error
            raise LlmRequestError(f"{code or 'ClientError'}: {message}") from error
        except BotoCoreError as error:
            raise LlmUnavailableError(f"Bedrock call failed: {error}") from error


def _parse_response(response: dict[str, Any], model_id: str, latency_ms: int) -> Completion:
    try:
        content = response["output"]["message"]["content"]
        text = "".join(block["text"] for block in content if "text" in block)
        usage = response["usage"]
        return Completion(
            text=text,
            model_id=model_id,
            stop_reason=response["stopReason"],
            input_tokens=usage["inputTokens"],
            output_tokens=usage["outputTokens"],
            latency_ms=latency_ms,
        )
    except (KeyError, TypeError) as error:
        raise LlmRequestError(f"Malformed Bedrock response: missing {error}") from error
