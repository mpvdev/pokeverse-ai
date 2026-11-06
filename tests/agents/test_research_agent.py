from collections.abc import Iterator
from typing import Any

import pytest

from pokeverse.agents import (
    POKEDEX_ANSWER_SCHEMA,
    RESEARCH_SYSTEM_PROMPT,
    Confidence,
    ResearchAgent,
)
from pokeverse.catalog import (
    BaseStats,
    Pokemon,
    PokemonCatalog,
    PokemonType,
    SqlitePokemonRepository,
)
from pokeverse.llm import Completion, LlmRequestError, ToolCall

PIKACHU = Pokemon(25, "pikachu", (PokemonType.ELECTRIC,), BaseStats(35, 55, 40, 50, 50, 90))


class ScriptedChat:
    """Returns a fixed completion and records what the agent sent."""

    def __init__(self, data: dict[str, Any], tool_calls: tuple[ToolCall, ...] = ()) -> None:
        self.completion = Completion("", "fake", "completed", 10, 5, 7, tool_calls, data)
        self.requests: list[dict[str, Any]] = []

    def complete(self, prompt: str, **kwargs: Any) -> Completion:
        self.requests.append({"prompt": prompt, **kwargs})
        return self.completion


@pytest.fixture
def catalog() -> Iterator[PokemonCatalog]:
    with SqlitePokemonRepository(":memory:") as repository:
        repository.save(PIKACHU)
        yield PokemonCatalog(repository)


def answer(pokemon: list[str], confidence: str = "high") -> dict[str, Any]:
    return {"answer": "Pikachu is Electric-type.", "pokemon": pokemon, "confidence": confidence}


LOOKUP = ToolCall("get_pokemon", {"name_or_id": "Pikachu"}, PIKACHU.to_dict())


def test_agent_sends_prompt_tools_and_schema(catalog: PokemonCatalog) -> None:
    chat = ScriptedChat(answer(["pikachu"]), (LOOKUP,))

    ResearchAgent(chat, catalog).ask("What type is Pikachu?")

    (request,) = chat.requests
    assert request["prompt"] == "What type is Pikachu?"
    assert request["system"] == RESEARCH_SYSTEM_PROMPT
    assert [tool.name for tool in request["tools"]] == ["get_pokemon", "get_type_matchups"]
    assert request["output_schema"] is POKEDEX_ANSWER_SCHEMA


def test_grounded_result(catalog: PokemonCatalog) -> None:
    result = ResearchAgent(ScriptedChat(answer(["pikachu"]), (LOOKUP,)), catalog).ask("q")

    assert result.answer.confidence is Confidence.HIGH
    assert result.looked_up == {"pikachu"}
    assert result.ungrounded == ()
    assert result.to_dict()["ungrounded"] == []


def test_claims_without_successful_lookup_are_ungrounded(catalog: PokemonCatalog) -> None:
    failed = ToolCall(
        "get_pokemon", {"name_or_id": "Raichu"}, {"error": "not_found", "message": ""}
    )
    chat = ScriptedChat(answer(["pikachu", "raichu"]), (LOOKUP, failed))

    result = ResearchAgent(chat, catalog).ask("q")

    assert result.ungrounded == ("raichu",)
    assert result.to_dict()["ungrounded"] == ["raichu"]


def test_matchup_lookup_grounds_the_pokemon(catalog: PokemonCatalog) -> None:
    matchup = ToolCall(
        "get_type_matchups",
        {"name_or_id": "Pikachu"},
        {"pokemon": PIKACHU.to_dict(), "weak_to": {"ground": 2.0}, "resists": {}, "immune_to": {}},
    )

    result = ResearchAgent(ScriptedChat(answer(["pikachu"]), (matchup,)), catalog).ask("q")

    assert result.looked_up == {"pikachu"}
    assert result.ungrounded == ()


def test_invalid_model_reply_raises_request_error(catalog: PokemonCatalog) -> None:
    chat = ScriptedChat(answer(["Pikachu!"]))

    with pytest.raises(LlmRequestError, match="failed validation"):
        ResearchAgent(chat, catalog).ask("q")
