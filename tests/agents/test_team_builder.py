from collections.abc import Iterator
from typing import Any

import pytest
from dotenv import find_dotenv, load_dotenv

from pokeverse.agents import TEAM_PROPOSAL_SCHEMA, TeamCompositionAgent, TeamProposal
from pokeverse.agents.team_builder import (
    TEAM_BUILDER_MAX_TOOL_ROUNDS,
    TEAM_BUILDER_SYSTEM_PROMPT,
)
from pokeverse.catalog import (
    BaseStats,
    Pokemon,
    PokemonCatalog,
    PokemonType,
    SqlitePokemonRepository,
)
from pokeverse.catalog.pokeapi import PokeApiClient
from pokeverse.llm import Completion, LlmRequestError, LlmSettings, OpenAIChat, ToolCall

T = PokemonType
STATS = BaseStats(hp=80, attack=80, defense=80, special_attack=80, special_defense=80, speed=80)
PIKACHU = Pokemon(pokedex_id=25, name="pikachu", types=(T.ELECTRIC,), stats=STATS)
CHARIZARD = Pokemon(pokedex_id=6, name="charizard", types=(T.FIRE, T.FLYING), stats=STATS)
BLASTOISE = Pokemon(pokedex_id=9, name="blastoise", types=(T.WATER,), stats=STATS)


class ScriptedChat:
    def __init__(self, data: dict[str, Any], tool_calls: tuple[ToolCall, ...] = ()) -> None:
        self.completion = Completion("", "fake", "completed", 10, 5, 7, tool_calls, data)
        self.requests: list[dict[str, Any]] = []

    def complete(self, prompt: str, **kwargs: Any) -> Completion:
        self.requests.append({"prompt": prompt, **kwargs})
        return self.completion


@pytest.fixture
def catalog() -> Iterator[PokemonCatalog]:
    with SqlitePokemonRepository(":memory:") as repository:
        for pokemon in (PIKACHU, CHARIZARD, BLASTOISE):
            repository.save(pokemon)
        yield PokemonCatalog(repository)


def proposal(*names: str) -> dict[str, Any]:
    return {
        "members": [{"name": name, "role": f"{name} role"} for name in names],
        "summary": "A small team.",
    }


def analyzed(*names: str) -> ToolCall:
    members = [{"name": name} for name in names]
    return ToolCall("analyze_team", {"names": list(names)}, {"team": {"members": members}})


def test_agent_sends_prompt_tools_and_schema(catalog: PokemonCatalog) -> None:
    chat = ScriptedChat(proposal("pikachu"))

    TeamCompositionAgent(chat, catalog).build("A team around Pikachu")

    (request,) = chat.requests
    assert request["prompt"] == "A team around Pikachu"
    assert request["system"] == TEAM_BUILDER_SYSTEM_PROMPT
    assert request["output_schema"] is TEAM_PROPOSAL_SCHEMA
    assert request["max_tool_rounds"] == TEAM_BUILDER_MAX_TOOL_ROUNDS
    assert [tool.name for tool in request["tools"]] == [
        "get_pokemon",
        "get_type_matchups",
        "analyze_team",
    ]


def test_result_is_analyzed_by_our_code(catalog: PokemonCatalog) -> None:
    chat = ScriptedChat(proposal("pikachu", "charizard", "blastoise"))

    result = TeamCompositionAgent(chat, catalog).build("q")

    assert result.analysis.team.names == ("pikachu", "charizard", "blastoise")
    assert [e.attacking_type for e in result.analysis.vulnerabilities] == [T.ELECTRIC]
    assert result.proposal.members[1].role == "charizard role"


@pytest.mark.parametrize(
    ("calls", "expected"),
    [
        ((analyzed("blastoise", "pikachu"),), True),
        ((analyzed("pikachu"),), False),
        ((analyzed("pikachu", "blastoise", "blastoise"),), False),
        ((), False),
    ],
)
def test_self_checked_requires_analysis_of_the_exact_final_team(
    catalog: PokemonCatalog, calls: tuple[ToolCall, ...], expected: bool
) -> None:
    chat = ScriptedChat(proposal("pikachu", "blastoise"), calls)

    result = TeamCompositionAgent(chat, catalog).build("q")

    assert result.self_checked is expected
    assert result.to_dict()["self_checked"] is expected


def test_invented_pokemon_is_rejected(catalog: PokemonCatalog) -> None:
    chat = ScriptedChat(proposal("pikachu", "pikablu"))

    with pytest.raises(LlmRequestError, match="does not exist"):
        TeamCompositionAgent(chat, catalog).build("q")


@pytest.mark.parametrize(
    "data",
    [
        {"members": [], "summary": "Empty."},
        {"members": [{"name": "Pikachu!", "role": "x"}], "summary": "s"},
        {"members": [{"name": "pikachu", "role": " "}], "summary": "s"},
        {"members": [{"name": "pikachu"}], "summary": "s"},
        {"members": [{"name": "pikachu", "role": "x"}] * 7, "summary": "s"},
        {"members": [{"name": "pikachu", "role": "x"}], "summary": ""},
    ],
)
def test_invalid_proposals_are_rejected(catalog: PokemonCatalog, data: dict[str, Any]) -> None:
    with pytest.raises(LlmRequestError, match="failed validation"):
        TeamCompositionAgent(ScriptedChat(data), catalog).build("q")


def test_proposal_round_trips() -> None:
    data = proposal("pikachu", "pikachu")

    assert TeamProposal.from_dict(data).to_dict() == data


def test_schema_is_strict_mode_compatible() -> None:
    schema = TEAM_PROPOSAL_SCHEMA.schema
    item = schema["properties"]["members"]["items"]

    for node in (schema, item):
        assert node["additionalProperties"] is False
        assert set(node["required"]) == set(node["properties"])


@pytest.mark.openai
def test_live_team_build() -> None:
    load_dotenv(find_dotenv(usecwd=True))
    with SqlitePokemonRepository(":memory:") as repository, PokeApiClient() as client:
        catalog = PokemonCatalog(repository, client)
        result = TeamCompositionAgent(OpenAIChat(LlmSettings.from_env()), catalog).build(
            "Build a team of 3 Pokémon around Pikachu."
        )

    assert "pikachu" in result.analysis.team.names
    assert len(result.analysis.team.members) == 3
    assert result.self_checked
