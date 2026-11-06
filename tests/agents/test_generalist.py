from collections.abc import Iterator
from typing import Any

import pytest

from pokeverse.agents.generalist import (
    GENERALIST_MAX_TOOL_ROUNDS,
    GENERALIST_SCHEMA,
    GENERALIST_SYSTEM_PROMPT,
    GeneralistAgent,
)
from pokeverse.catalog import PokemonCatalog, SqlitePokemonRepository
from pokeverse.llm import Completion, LlmRequestError


class ScriptedChat:
    def __init__(self, data: dict[str, Any] | None) -> None:
        self.data = data
        self.requests: list[dict[str, Any]] = []

    def complete(self, prompt: str, **kwargs: Any) -> Completion:
        self.requests.append({"prompt": prompt, **kwargs})
        return Completion("", "fake", "completed", 40, 10, 5, (), self.data)


@pytest.fixture
def catalog() -> Iterator[PokemonCatalog]:
    with SqlitePokemonRepository(":memory:") as repository:
        yield PokemonCatalog(repository)


def test_generalist_has_every_tool_and_one_schema(catalog: PokemonCatalog) -> None:
    chat = ScriptedChat({"answer": "Pikachu leads.", "team": ["pikachu"]})

    result = GeneralistAgent(chat, catalog).run("Team around Pikachu")

    (request,) = chat.requests
    assert request["system"] == GENERALIST_SYSTEM_PROMPT
    assert request["output_schema"] is GENERALIST_SCHEMA
    assert request["max_tool_rounds"] == GENERALIST_MAX_TOOL_ROUNDS
    assert [t.name for t in request["tools"]] == [
        "get_pokemon",
        "get_type_matchups",
        "analyze_team",
    ]
    assert result.team == ("pikachu",)
    assert result.to_dict() == {"answer": "Pikachu leads.", "team": ["pikachu"]}


@pytest.mark.parametrize("data", [None, {"answer": " ", "team": []}, {"answer": "x"}])
def test_invalid_reply_raises_with_usage(catalog: PokemonCatalog, data: Any) -> None:
    with pytest.raises(LlmRequestError, match="failed validation") as raised:
        GeneralistAgent(ScriptedChat(data), catalog).run("q")

    assert raised.value.completion is not None
    assert raised.value.completion.total_tokens == 50
