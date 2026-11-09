"""Minimal OpenAI chat client built on the Responses API."""

import json
import os
import time
from collections.abc import Mapping, Sequence
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
from pydantic import BaseModel, ValidationError

from pokeverse.llm.config import LlmSettings
from pokeverse.llm.structured import OutputSchema
from pokeverse.llm.tools import Tool, ToolCall

DEFAULT_MAX_TOOL_ROUNDS = 5


class LlmError(Exception):
    """Base class for LLM inference errors."""


class LlmAuthError(LlmError):
    """Missing/invalid credentials or no access to the model."""


class LlmUnavailableError(LlmError):
    """Transient failure: throttling, service outage, timeouts, network."""


class LlmRequestError(LlmError):
    """The request was rejected or the reply was malformed.

    ``completion`` holds the usage and tool calls spent before the failure, when any.
    """

    def __init__(self, message: str, completion: Completion | None = None) -> None:
        super().__init__(message)
        self.completion = completion


@dataclass(frozen=True, slots=True)
class Completion:
    """A model reply plus the metadata needed to reason about cost and latency."""

    text: str
    model_id: str
    stop_reason: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    tool_calls: tuple[ToolCall, ...] = ()
    data: dict[str, Any] | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def parse_reply[M: BaseModel](
    model: type[M], completion: Completion, what: str = "Model reply"
) -> M:
    """Validate a structured reply as JSON (strict: no coercion); failures keep the usage."""
    try:
        return model.model_validate_json(json.dumps(completion.data or {}))
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(map(str, e['loc'])) or 'reply'}: {e['msg'].removeprefix('Value error, ')}"
            for e in error.errors()
        )
        raise LlmRequestError(
            f"{what} failed validation: {problems}", completion=completion
        ) from error


class OpenAIChat:
    """Text completion via the OpenAI Responses API, with optional tool calling.

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
        tools: Sequence[Tool] = (),
        max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
        output_schema: OutputSchema | None = None,
    ) -> Completion:
        """Answer ``prompt``, running any requested ``tools`` until the model replies.

        With ``output_schema``, the final reply is constrained to that JSON Schema and
        parsed into ``Completion.data``.
        """
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
        if tools:
            request["tools"] = [_tool_schema(tool) for tool in tools]
        if output_schema is not None:
            request["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": output_schema.name,
                    "schema": dict(output_schema.schema),
                    "strict": True,
                }
            }

        tools_by_name = {tool.name: tool for tool in tools}
        conversation: list[Any] = [{"role": "user", "content": prompt}]
        tool_calls: list[ToolCall] = []
        input_tokens = output_tokens = 0
        started = time.perf_counter()

        try:
            for _ in range(max_tool_rounds + 1):
                response = self._call({**request, "input": list(conversation) if tools else prompt})
                round_input, round_output = _usage(response)
                input_tokens += round_input
                output_tokens += round_output

                function_calls = _function_calls(response) if tools else []
                if not function_calls:
                    return _completion(
                        response,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        latency_ms=round((time.perf_counter() - started) * 1000),
                        tool_calls=tuple(tool_calls),
                        data=_structured_data(response) if output_schema else None,
                    )

                # Reasoning items must be sent back together with the tool results.
                _raise_if_cut_off(response)
                conversation += response.output
                for item in function_calls:
                    call = _run_tool(tools_by_name, item)
                    tool_calls.append(call)
                    conversation.append(
                        {
                            "type": "function_call_output",
                            "call_id": item.call_id,
                            "output": json.dumps(call.output),
                        }
                    )

            raise LlmRequestError(f"Model still requesting tools after {max_tool_rounds} rounds")
        except LlmRequestError as error:
            if error.completion is None:
                error.completion = Completion(
                    text="",
                    model_id=settings.model_id,
                    stop_reason="failed",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=round((time.perf_counter() - started) * 1000),
                    tool_calls=tuple(tool_calls),
                )
            raise

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


def _tool_schema(tool: Tool) -> dict[str, Any]:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": dict(tool.parameters),
        "strict": True,
    }


def _function_calls(response: Any) -> list[Any]:
    try:
        return [item for item in response.output if item.type == "function_call"]
    except (AttributeError, TypeError) as error:
        raise LlmRequestError(f"Malformed OpenAI response: {error}") from error


def _run_tool(tools: Mapping[str, Tool], item: Any) -> ToolCall:
    try:
        arguments = json.loads(item.arguments)
    except json.JSONDecodeError as error:
        raise LlmRequestError(f"Model sent invalid JSON arguments to {item.name!r}") from error
    tool = tools.get(item.name)
    if tool is None:
        output = {"error": "unknown_tool", "message": f"No tool named {item.name!r}"}
    else:
        output = tool.handler(**arguments)
    return ToolCall(name=item.name, arguments=arguments, output=output)


def _usage(response: Any) -> tuple[int, int]:
    try:
        usage = response.usage
        if usage is None:
            raise TypeError("usage is null")
        return usage.input_tokens, usage.output_tokens
    except (AttributeError, TypeError) as error:
        raise LlmRequestError(f"Malformed OpenAI response: {error}") from error


def _raise_if_cut_off(response: Any) -> None:
    """Truncated tool arguments or JSON replies are unusable, unlike truncated prose."""
    if getattr(response, "status", None) == "incomplete":
        details = getattr(response, "incomplete_details", None)
        reason = getattr(details, "reason", None) or "unknown reason"
        raise LlmRequestError(f"Model reply was cut off ({reason}); try a larger --max-tokens")


def _structured_data(response: Any) -> dict[str, Any]:
    _raise_if_cut_off(response)
    try:
        for item in response.output:
            if item.type == "message":
                for part in item.content:
                    if part.type == "refusal":
                        raise LlmRequestError(f"Model refused to answer: {part.refusal}")
        data = json.loads(response.output_text)
    except (AttributeError, TypeError) as error:
        raise LlmRequestError(f"Malformed OpenAI response: {error}") from error
    except json.JSONDecodeError as error:
        raise LlmRequestError("Structured reply is not valid JSON") from error
    if not isinstance(data, dict):
        raise LlmRequestError("Structured reply is not a JSON object")
    return data


def _completion(
    response: Any,
    *,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    tool_calls: tuple[ToolCall, ...],
    data: dict[str, Any] | None,
) -> Completion:
    try:
        return Completion(
            text=response.output_text,
            model_id=response.model,
            stop_reason=response.status,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            tool_calls=tool_calls,
            data=data,
        )
    except AttributeError as error:
        raise LlmRequestError(f"Malformed OpenAI response: {error}") from error
