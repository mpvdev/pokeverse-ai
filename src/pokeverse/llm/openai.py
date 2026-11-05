"""Minimal OpenAI chat client built on the Responses API."""

import os
import time
from dataclasses import dataclass, replace
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    InternalServerError,
    OpenAI,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
)

from pokeverse.llm.config import LlmSettings


class LlmError(Exception):
    """Base class for LLM inference errors."""


class LlmAuthError(LlmError):
    """Missing/invalid credentials or no access to the model."""


class LlmUnavailableError(LlmError):
    """Transient failure: throttling, service outage, timeouts, network."""


class LlmRequestError(LlmError):
    """The request was rejected or the reply was malformed."""


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


class OpenAIChat:
    """Single-turn text completion via the OpenAI Responses API.

    Pass ``client`` to inject a preconfigured or fake OpenAI client in tests.
    """

    def __init__(self, settings: LlmSettings | None = None, client: Any | None = None) -> None:
        self.settings = settings or LlmSettings.from_env()
        if client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                raise LlmAuthError(
                    "OPENAI_API_KEY is not set. Add it to .env or export it before retrying."
                )
            client = OpenAI(timeout=30.0, max_retries=0)
        self._client = client

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
            "model": settings.model_id,
            "input": prompt,
            "max_output_tokens": settings.max_tokens,
            "reasoning": {"effort": settings.reasoning_effort},
        }
        # The API rejects temperature unless reasoning is disabled.
        if settings.reasoning_effort == "none":
            request["temperature"] = settings.temperature
        if system:
            request["instructions"] = system

        started = time.perf_counter()
        response = self._call(request)
        latency_ms = round((time.perf_counter() - started) * 1000)
        return _parse_response(response, latency_ms)

    def _call(self, request: dict[str, Any]) -> Any:
        try:
            return self._client.responses.create(**request)
        except (AuthenticationError, PermissionDeniedError) as error:
            raise LlmAuthError(str(error)) from error
        except (RateLimitError, APIConnectionError, InternalServerError) as error:
            raise LlmUnavailableError(str(error)) from error
        except APIStatusError as error:
            if error.status_code in {408, 409, 429} or error.status_code >= 500:
                raise LlmUnavailableError(str(error)) from error
            raise LlmRequestError(str(error)) from error
        except OpenAIError as error:
            raise LlmRequestError(str(error)) from error


def _parse_response(response: Any, latency_ms: int) -> Completion:
    try:
        usage = response.usage
        if usage is None:
            raise TypeError("usage is null")
        return Completion(
            text=response.output_text,
            model_id=response.model,
            stop_reason=response.status,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=latency_ms,
        )
    except (AttributeError, TypeError) as error:
        raise LlmRequestError(f"Malformed OpenAI response: {error}") from error
