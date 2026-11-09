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
    OutputSchema,
    Tool,
    ToolCall,
)

SETTINGS = LlmSettings(model_id="test-model", temperature=0.3, max_tokens=64)


def openai_response(
    text: str = "Pikachu is Electric-type.",
    output: list[Any] | None = None,
    usage: tuple[int, int] = (12, 7),
    status: str = "completed",
    incomplete_reason: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        output_text=text,
        output=output or [],
        model="test-model",
        status=status,
        incomplete_details=SimpleNamespace(reason=incomplete_reason) if incomplete_reason else None,
        usage=SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1]),
    )


def function_call(
    arguments: str = '{"name_or_id": "pikachu"}', name: str = "get_pokemon", call_id: str = "c1"
) -> SimpleNamespace:
    return SimpleNamespace(type="function_call", call_id=call_id, name=name, arguments=arguments)


class FakeResponses:
    def __init__(self, responses: list[Any], error: Exception | None = None) -> None:
        self.responses = responses
        self.error = error
        self.requests: list[dict[str, Any]] = []

    def create(self, **request: Any) -> Any:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, *responses: Any, error: Exception | None = None) -> None:
        self.responses = FakeResponses(list(responses), error)


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
    assert completion.data is None
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


PIKACHU = {"pokedex_id": 25, "name": "pikachu", "types": ["electric"]}


def pokemon_tool(calls: list[str] | None = None) -> Tool:
    def get_pokemon(name_or_id: str) -> dict[str, Any]:
        if calls is not None:
            calls.append(name_or_id)
        return PIKACHU

    return Tool(
        name="get_pokemon",
        description="Look up a Pokémon.",
        parameters={
            "type": "object",
            "properties": {"name_or_id": {"type": "string"}},
            "required": ["name_or_id"],
            "additionalProperties": False,
        },
        handler=get_pokemon,
    )


def test_tool_call_round_trip() -> None:
    reasoning = SimpleNamespace(type="reasoning", id="rs_1")
    call = function_call()
    client = FakeClient(
        openai_response("", output=[reasoning, call], usage=(10, 5)),
        openai_response("Pikachu is Electric-type.", usage=(20, 7)),
    )
    handled: list[str] = []
    chat = OpenAIChat(SETTINGS, client=client)

    completion = chat.complete("What type is Pikachu?", tools=[pokemon_tool(handled)])

    assert completion.text == "Pikachu is Electric-type."
    assert (completion.input_tokens, completion.output_tokens) == (30, 12)
    assert completion.tool_calls == (ToolCall("get_pokemon", {"name_or_id": "pikachu"}, PIKACHU),)
    assert handled == ["pikachu"]

    first, second = client.responses.requests
    assert first["tools"][0]["name"] == "get_pokemon"
    assert first["tools"][0]["strict"] is True
    assert first["input"] == [{"role": "user", "content": "What type is Pikachu?"}]
    assert second["input"] == [
        {"role": "user", "content": "What type is Pikachu?"},
        reasoning,
        call,
        {
            "type": "function_call_output",
            "call_id": "c1",
            "output": '{"pokedex_id": 25, "name": "pikachu", "types": ["electric"]}',
        },
    ]


def test_unknown_tool_returns_error_to_model() -> None:
    client = FakeClient(
        openai_response("", output=[function_call(name="get_weather", arguments="{}")]),
        openai_response("I can only look up Pokémon."),
    )
    chat = OpenAIChat(SETTINGS, client=client)

    completion = chat.complete("Weather?", tools=[pokemon_tool()])

    assert completion.tool_calls[0].output["error"] == "unknown_tool"
    assert "unknown_tool" in client.responses.requests[1]["input"][-1]["output"]


def test_tool_loop_is_bounded() -> None:
    client = FakeClient(*[openai_response("", output=[function_call()]) for _ in range(3)])
    chat = OpenAIChat(SETTINGS, client=client)

    with pytest.raises(LlmRequestError, match="2 rounds") as raised:
        chat.complete("Loop forever", tools=[pokemon_tool()], max_tool_rounds=2)

    assert len(client.responses.requests) == 3
    partial = raised.value.completion
    assert partial is not None
    assert (partial.input_tokens, partial.output_tokens) == (36, 21)
    assert len(partial.tool_calls) == 3


def test_invalid_tool_arguments_raise_request_error() -> None:
    client = FakeClient(openai_response("", output=[function_call(arguments="{not json")]))
    chat = OpenAIChat(SETTINGS, client=client)

    with pytest.raises(LlmRequestError, match="invalid JSON"):
        chat.complete("What type is Pikachu?", tools=[pokemon_tool()])


def test_truncated_tool_call_reports_cut_off() -> None:
    truncated = openai_response(
        "",
        output=[function_call(arguments='{"name_or')],
        status="incomplete",
        incomplete_reason="max_output_tokens",
    )
    chat = OpenAIChat(SETTINGS, client=FakeClient(truncated))

    with pytest.raises(LlmRequestError, match=r"cut off \(max_output_tokens\)"):
        chat.complete("What type is Pikachu?", tools=[pokemon_tool()])


NUMBER_SCHEMA = OutputSchema(
    name="pokedex_number",
    schema={
        "type": "object",
        "properties": {"number": {"type": "integer"}},
        "required": ["number"],
        "additionalProperties": False,
    },
)


def test_structured_output_is_requested_and_parsed() -> None:
    client = FakeClient(openai_response('{"number": 25}'))
    chat = OpenAIChat(SETTINGS, client=client)

    completion = chat.complete("Pikachu's number?", output_schema=NUMBER_SCHEMA)

    assert completion.data == {"number": 25}
    assert client.responses.requests[0]["text"] == {
        "format": {
            "type": "json_schema",
            "name": "pokedex_number",
            "schema": dict(NUMBER_SCHEMA.schema),
            "strict": True,
        }
    }


def test_structured_output_after_tool_call() -> None:
    client = FakeClient(
        openai_response("", output=[function_call()]),
        openai_response('{"number": 25}'),
    )
    chat = OpenAIChat(SETTINGS, client=client)

    completion = chat.complete(
        "Pikachu's number?", tools=[pokemon_tool()], output_schema=NUMBER_SCHEMA
    )

    assert completion.data == {"number": 25}
    assert len(completion.tool_calls) == 1


def refusal_message(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="message", content=[SimpleNamespace(type="refusal", refusal=text)])


@pytest.mark.parametrize(
    ("response", "match"),
    [
        (
            openai_response('{"num', status="incomplete", incomplete_reason="max_output_tokens"),
            r"cut off \(max_output_tokens\)",
        ),
        (openai_response("", output=[refusal_message("I can't help.")]), "refused"),
        (openai_response("not json"), "not valid JSON"),
        (openai_response("[25]"), "not a JSON object"),
    ],
)
def test_unusable_structured_reply_raises_request_error(
    response: SimpleNamespace, match: str
) -> None:
    chat = OpenAIChat(SETTINGS, client=FakeClient(response))

    with pytest.raises(LlmRequestError, match=match):
        chat.complete("Pikachu's number?", output_schema=NUMBER_SCHEMA)


@pytest.mark.openai
def test_live_openai_completion() -> None:
    load_dotenv(find_dotenv(usecwd=True))
    completion = OpenAIChat(LlmSettings.from_env()).complete(
        "Reply with exactly the word: pong", temperature=0.0, max_tokens=16
    )

    assert "pong" in completion.text.lower()
    assert completion.input_tokens > 0
    assert completion.output_tokens > 0


@pytest.mark.openai
def test_live_openai_tool_call() -> None:
    load_dotenv(find_dotenv(usecwd=True))
    handled: list[str] = []
    completion = OpenAIChat(LlmSettings.from_env()).complete(
        "What is Pikachu's National Pokédex number?", tools=[pokemon_tool(handled)]
    )

    assert handled
    assert completion.tool_calls[0].name == "get_pokemon"
    assert "25" in completion.text


@pytest.mark.openai
def test_live_openai_structured_output() -> None:
    load_dotenv(find_dotenv(usecwd=True))
    completion = OpenAIChat(LlmSettings.from_env()).complete(
        "What is Pikachu's National Pokédex number?",
        tools=[pokemon_tool()],
        output_schema=NUMBER_SCHEMA,
    )

    assert completion.data == {"number": 25}
