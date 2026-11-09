from collections.abc import Iterator
from typing import Any

import pytest

from pokeverse.agents import Delegation, SupervisorResult
from pokeverse.agents.generalist import GENERALIST_SYSTEM_PROMPT
from pokeverse.catalog import (
    BaseStats,
    Pokemon,
    PokemonCatalog,
    PokemonType,
    SqlitePokemonRepository,
    StaticSource,
)
from pokeverse.evals.compare import (
    COMPARE_CASES,
    CompareCase,
    check,
    mentions,
    observed_team,
    run_case,
)
from pokeverse.llm import Completion
from pokeverse.teams import Team, analyze_team

T = PokemonType
STATS = BaseStats(hp=80, attack=80, defense=80, special_attack=80, special_defense=80, speed=80)
GARCHOMP = Pokemon(pokedex_id=445, name="garchomp", types=(T.DRAGON, T.GROUND), stats=STATS)
EMPOLEON = Pokemon(pokedex_id=395, name="empoleon", types=(T.WATER, T.STEEL), stats=STATS)
CORVIKNIGHT = Pokemon(pokedex_id=823, name="corviknight", types=(T.FLYING, T.STEEL), stats=STATS)
CLEFABLE = Pokemon(pokedex_id=36, name="clefable", types=(T.FAIRY,), stats=STATS)
ARCANINE = Pokemon(pokedex_id=59, name="arcanine", types=(T.FIRE,), stats=STATS)
FLYGON = Pokemon(pokedex_id=330, name="flygon", types=(T.GROUND, T.DRAGON), stats=STATS)

TEAM_CASE = CompareCase(
    "t",
    "q",
    must_match=(r"ice[^.\n]{0,20}4\s*[×x]|4\s*[×x][^.\n]{0,20}ice",),
    team_size=3,
    must_include=("garchomp",),
    must_cover=(T.ICE, T.DRAGON),
    max_vulnerabilities=0,
)
# Empoleon (Water/Steel) takes 1/4 from Ice and resists Dragon; Clefable is immune to Dragon.
GOOD_TEAM = Team((GARCHOMP, EMPOLEON, CLEFABLE))
GOOD_ANSWER = "Garchomp takes 4× from Ice. Team: Garchomp, Empoleon, Clefable."


def run_check(case: CompareCase, answer: str, team: Team | None) -> tuple[str, ...]:
    return check(case, answer, team, analyze_team(team) if team else None)


def test_good_team_passes() -> None:
    assert run_check(TEAM_CASE, GOOD_ANSWER, GOOD_TEAM) == ()


@pytest.mark.parametrize(
    ("answer", "team", "failure"),
    [
        ("Garchomp is weak to Ice.", GOOD_TEAM, "does not match"),
        (GOOD_ANSWER, None, "no team produced"),
        (GOOD_ANSWER, Team((GARCHOMP, EMPOLEON)), "team has 2 members, expected 3"),
        (GOOD_ANSWER, Team((CLEFABLE, EMPOLEON, ARCANINE)), "team is missing ['garchomp']"),
        (GOOD_ANSWER, Team((GARCHOMP, CORVIKNIGHT, CLEFABLE)), "nobody resists ice"),
        (GOOD_ANSWER, Team((GARCHOMP, FLYGON, EMPOLEON)), "vulnerabilities > 0"),
        ("Garchomp takes 4× from Ice. Team: Garchomp, Clefable.", GOOD_TEAM, "empoleon"),
    ],
)
def test_check_reports_failures(answer: str, team: Team | None, failure: str) -> None:
    failures = run_check(TEAM_CASE, answer, team)

    assert any(failure in message for message in failures), failures


def test_only_types() -> None:
    case = CompareCase("f", "q", team_size=2, only_types=frozenset({T.FIRE}))

    failures = run_check(case, "Arcanine and Garchomp.", Team((ARCANINE, GARCHOMP)))

    assert failures == ("members outside the allowed types: ['garchomp']",)


def test_mentions_accepts_spaced_names() -> None:
    assert mentions("Try Mr. Mime", "mr-mime") is False
    assert mentions("Try Mr Mime", "mr-mime") is True
    assert mentions("Gouging Fire leads", "gouging-fire") is True


def delegation(agent: str, output: dict[str, Any] | None) -> Delegation:
    return Delegation(agent, "task", output, None if output else "boom")


def test_observed_team_prefers_optimizer_output() -> None:
    completion = Completion("answer", "fake", "completed", 1, 1, 1)
    built = {"members": [{"name": "garchomp", "role": "x"}, {"name": "arcanine", "role": "y"}]}
    result = SupervisorResult(
        "answer",
        (
            delegation("research", {"answer": "x"}),
            delegation("team_builder", built),
            delegation("team_optimizer", {"final_members": ["garchomp", "clefable"]}),
        ),
        completion,
    )
    builder_only = SupervisorResult("a", result.delegations[:2], completion)
    failed_optimizer = SupervisorResult(
        "a", (*result.delegations[:2], delegation("team_optimizer", None)), completion
    )

    assert observed_team(result) == ["garchomp", "clefable"]
    assert observed_team(builder_only) == ["garchomp", "arcanine"]
    assert observed_team(failed_optimizer) == ["garchomp", "arcanine"]


class ScriptedGeneralist:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    def complete(self, prompt: str, **kwargs: Any) -> Completion:
        assert kwargs["system"] == GENERALIST_SYSTEM_PROMPT
        return Completion("", "fake", "completed", 300, 100, 5, (), self.data)


@pytest.fixture
def catalog() -> Iterator[PokemonCatalog]:
    with SqlitePokemonRepository(":memory:") as repository:
        yield PokemonCatalog(repository, StaticSource([GARCHOMP, EMPOLEON, CLEFABLE]))


def test_run_case_single_agent(catalog: PokemonCatalog) -> None:
    chat = ScriptedGeneralist({"answer": GOOD_ANSWER, "team": list(GOOD_TEAM.names)})

    outcome = run_case("single", TEAM_CASE, chat, catalog)

    assert outcome.passed, outcome.failures
    assert outcome.tokens == 400
    assert outcome.to_dict()["team"] == ["garchomp", "empoleon", "clefable"]
    assert outcome.to_dict()["score"] == list(analyze_team(GOOD_TEAM).score)


def test_run_case_reports_invented_member(catalog: PokemonCatalog) -> None:
    chat = ScriptedGeneralist({"answer": GOOD_ANSWER, "team": ["garchomp", "pikablu", "clefable"]})

    outcome = run_case("single", TEAM_CASE, chat, catalog)

    assert outcome.failures[0].startswith("invalid team")
    assert "no team produced" in outcome.failures


def test_run_case_request_error_fails_with_tokens(catalog: PokemonCatalog) -> None:
    outcome = run_case("single", TEAM_CASE, ScriptedGeneralist({"answer": ""}), catalog)

    assert not outcome.passed
    assert outcome.failures[0].startswith("request error")
    assert outcome.tokens == 400


def fake_supervisor(monkeypatch: pytest.MonkeyPatch, delegations: tuple[Delegation, ...]) -> None:
    import pokeverse.evals.compare as compare

    class FakeSupervisor:
        def __init__(self, chat: object, catalog: object, *, optimize: bool) -> None:
            pass

        def run(self, request: str) -> SupervisorResult:
            completion = Completion(GOOD_ANSWER, "fake", "completed", 100, 50, 5)
            return SupervisorResult(GOOD_ANSWER, delegations, completion)

    monkeypatch.setattr(compare, "Supervisor", FakeSupervisor)


BUILT = {"members": [{"name": name, "role": "r"} for name in GOOD_TEAM.names]}


def test_recovered_specialist_error_does_not_fail_the_run(
    monkeypatch: pytest.MonkeyPatch, catalog: PokemonCatalog
) -> None:
    fake_supervisor(
        monkeypatch, (delegation("team_builder", None), delegation("team_builder", BUILT))
    )

    outcome = run_case("multi", TEAM_CASE, ScriptedGeneralist({}), catalog)

    assert outcome.passed, outcome.failures


def test_unrecovered_specialist_error_explains_the_failure(
    monkeypatch: pytest.MonkeyPatch, catalog: PokemonCatalog
) -> None:
    fake_supervisor(monkeypatch, (delegation("team_builder", None),))

    outcome = run_case("multi", TEAM_CASE, ScriptedGeneralist({}), catalog)

    assert outcome.failures[:2] == ("team_builder failed: boom", "no team produced")


def test_case_ids_are_unique() -> None:
    ids = [case.id for case in COMPARE_CASES]

    assert len(ids) == len(set(ids))
