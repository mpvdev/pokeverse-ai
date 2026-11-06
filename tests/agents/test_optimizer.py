from collections.abc import Iterator
from typing import Any

import pytest

from pokeverse.agents import TeamOptimizationAgent
from pokeverse.agents.optimizer import OPTIMIZATION_SCHEMA, OPTIMIZER_SYSTEM_PROMPT, verdict
from pokeverse.catalog import Pokemon, PokemonCatalog, PokemonType, SqlitePokemonRepository
from pokeverse.llm import Completion, LlmRequestError
from pokeverse.teams import Team

T = PokemonType
RESHIRAM = Pokemon(643, "reshiram", (T.DRAGON, T.FIRE))
TURTONATOR = Pokemon(776, "turtonator", (T.FIRE, T.DRAGON))
GOUGING_FIRE = Pokemon(1020, "gouging-fire", (T.FIRE, T.DRAGON))
VOLCANION = Pokemon(721, "volcanion", (T.FIRE, T.WATER))
ARCANINE = Pokemon(59, "arcanine", (T.FIRE,))
CORVIKNIGHT = Pokemon(823, "corviknight", (T.FLYING, T.STEEL))
FIRE_TEAM = Team((RESHIRAM, TURTONATOR, GOUGING_FIRE, VOLCANION))


class ScriptedChat:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.requests: list[dict[str, Any]] = []

    def complete(self, prompt: str, **kwargs: Any) -> Completion:
        self.requests.append({"prompt": prompt, **kwargs})
        return Completion("", "fake", "completed", 50, 20, 9, (), self.data)


@pytest.fixture
def catalog() -> Iterator[PokemonCatalog]:
    with SqlitePokemonRepository(":memory:") as repository:
        for pokemon in (RESHIRAM, TURTONATOR, GOUGING_FIRE, VOLCANION, ARCANINE, CORVIKNIGHT):
            repository.save(pokemon)
        yield PokemonCatalog(repository)


def reply(swaps: list[tuple[str, str]] = (), claims: list[tuple[str, str, str]] = ()) -> dict:
    return {
        "claims": [{"member": m, "attacking_type": t, "claimed": c} for m, t, c in claims],
        "swaps": [{"out": o, "in": i, "reason": f"{o} -> {i}"} for o, i in swaps],
        "critique": "Too many Fire/Dragons.",
    }


def optimize(catalog: PokemonCatalog, data: dict, team: Team = FIRE_TEAM, **kwargs: Any):
    chat = ScriptedChat(data)
    return TeamOptimizationAgent(chat, catalog).optimize(team, **kwargs), chat


def test_agent_sends_prompt_tools_and_schema(catalog: PokemonCatalog) -> None:
    _, chat = optimize(
        catalog, reply(), goal="Fire-only", keep=["Reshiram"], notes="n", facts="Verified facts"
    )

    (request,) = chat.requests
    assert request["system"] == OPTIMIZER_SYSTEM_PROMPT
    assert request["output_schema"] is OPTIMIZATION_SCHEMA
    assert [t.name for t in request["tools"]] == [
        "get_pokemon",
        "get_type_matchups",
        "score_team",
    ]
    prompt = request["prompt"]
    assert "Team: reshiram, turtonator, gouging-fire, volcanion" in prompt
    assert "Goal: Fire-only" in prompt
    assert "Keep: reshiram" in prompt
    assert "Verified facts" in prompt and "not claims to extract" in prompt


def test_improving_swap_is_accepted(catalog: PokemonCatalog) -> None:
    result, _ = optimize(catalog, reply([("gouging-fire", "arcanine")]))

    (swap,) = result.swaps
    assert swap.accepted
    assert result.final.team.names == ("reshiram", "turtonator", "arcanine", "volcanion")
    assert result.final.score < result.original.score
    dragon = next(e for e in result.final.vulnerabilities if e.attacking_type is T.DRAGON)
    assert dragon.weak == ("reshiram", "turtonator")


def test_non_improving_swap_is_rejected(catalog: PokemonCatalog) -> None:
    result, _ = optimize(catalog, reply([("gouging-fire", "turtonator")]))

    (swap,) = result.swaps
    assert not swap.accepted
    assert swap.verdict.startswith("no improvement")
    assert result.final == result.original


@pytest.mark.parametrize(
    ("swap", "keep", "message"),
    [
        (("reshiram", "arcanine"), ["Reshiram"], "keep this member"),
        (("charizard", "arcanine"), [], "not on the team"),
        (("gouging-fire", "pikablu"), [], "could not look up"),
    ],
)
def test_invalid_swaps_are_rejected(
    catalog: PokemonCatalog, swap: tuple[str, str], keep: list[str], message: str
) -> None:
    result, _ = optimize(catalog, reply([swap]), keep=keep)

    assert not result.swaps[0].accepted
    assert message in result.swaps[0].verdict
    assert result.final.team == FIRE_TEAM


def test_swaps_apply_in_sequence(catalog: PokemonCatalog) -> None:
    result, _ = optimize(
        catalog, reply([("gouging-fire", "arcanine"), ("gouging-fire", "corviknight")])
    )

    first, second = result.swaps
    assert first.accepted
    assert not second.accepted and second.verdict == "not on the team"


def test_claims_are_checked_against_the_type_chart(catalog: PokemonCatalog) -> None:
    team = Team((CORVIKNIGHT,))
    claims = [
        ("corviknight", "ice", "resists"),
        ("corviknight", "ground", "immune"),
        ("arcanine", "water", "weak"),
        ("garchomp", "ice", "weak"),
    ]

    result, _ = optimize(catalog, reply(claims=claims), team=team)

    wrong, right, off_team, unknown = result.claims
    assert (wrong.actual, wrong.multiplier, wrong.correct) == ("neutral", 1.0, False)
    assert (right.actual, right.multiplier, right.correct) == ("immune", 0.0, True)
    assert (off_team.actual, off_team.correct) == ("weak", True)
    assert (unknown.actual, unknown.correct) == (None, False)
    assert result.incorrect_claims == (wrong, unknown)


@pytest.mark.parametrize(
    ("multiplier", "expected"),
    [(0.0, "immune"), (0.25, "resists"), (1.0, "neutral"), (4.0, "weak")],
)
def test_verdict(multiplier: float, expected: str) -> None:
    assert verdict(multiplier) == expected


def test_malformed_reply_raises_with_partial_usage(catalog: PokemonCatalog) -> None:
    with pytest.raises(LlmRequestError, match="failed validation") as raised:
        optimize(catalog, {"swaps": [], "critique": "x"})

    assert raised.value.completion is not None
    assert raised.value.completion.total_tokens == 70


def test_to_dict(catalog: PokemonCatalog) -> None:
    result, _ = optimize(catalog, reply([("gouging-fire", "arcanine")]))

    data = result.to_dict()
    assert data["original_members"] == ["reshiram", "turtonator", "gouging-fire", "volcanion"]
    assert data["final_members"] == ["reshiram", "turtonator", "arcanine", "volcanion"]
    assert data["final_score"] < data["original_score"]
    assert data["swaps"][0]["accepted"] is True
    assert "exposures" not in data["final_analysis"]


def test_schema_is_strict_mode_compatible() -> None:
    schema = OPTIMIZATION_SCHEMA.schema
    nodes = [
        schema,
        schema["properties"]["claims"]["items"],
        schema["properties"]["swaps"]["items"],
    ]

    for node in nodes:
        assert node["additionalProperties"] is False
        assert set(node["required"]) == set(node["properties"])
