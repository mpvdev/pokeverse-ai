"""Single- vs multi-agent comparison on fixed tasks, scored by deterministic checks."""

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pokeverse.agents.generalist import GeneralistAgent
from pokeverse.agents.research import ChatModel
from pokeverse.agents.supervisor import Supervisor, SupervisorResult
from pokeverse.agents.tools import normalize_pokemon_identifier
from pokeverse.catalog import PokemonCatalog, PokemonNotInCatalogError, PokemonType
from pokeverse.catalog.type_chart import effectiveness
from pokeverse.llm import LlmRequestError
from pokeverse.teams import Team, TeamAnalysis, analyze_team

T = PokemonType
SYSTEMS = ("single", "multi", "multi+opt")


@dataclass(frozen=True, slots=True)
class CompareCase:
    id: str
    request: str
    # Case-insensitive regular expressions the answer must match.
    must_match: tuple[str, ...] = ()
    # None: no team expected.
    team_size: int | None = None
    must_include: tuple[str, ...] = ()
    # Every member must have at least one of these types.
    only_types: frozenset[PokemonType] = frozenset()
    # Attack types at least one member must resist or be immune to.
    must_cover: tuple[PokemonType, ...] = ()
    max_vulnerabilities: int | None = None


COMPARE_CASES: tuple[CompareCase, ...] = (
    CompareCase(
        "garchomp-team",
        "What is Garchomp weak to? Then build me a team of 4 with Garchomp that covers "
        "those weaknesses.",
        must_match=(r"ice[^.\n]{0,20}4\s*[×x]|4\s*[×x][^.\n]{0,20}ice", r"dragon", r"fairy"),
        team_size=4,
        must_include=("garchomp",),
        must_cover=(T.ICE, T.DRAGON, T.FAIRY),
        max_vulnerabilities=0,
    ),
    CompareCase(
        "fire-only",
        "Build a team of 4 Fire-type Pokémon only, with as few shared weaknesses as possible.",
        team_size=4,
        only_types=frozenset({T.FIRE}),
        max_vulnerabilities=2,
    ),
    CompareCase(
        "water-trio",
        "Build a team of 3 Water-type Pokémon that do not share a weakness.",
        team_size=3,
        only_types=frozenset({T.WATER}),
        max_vulnerabilities=0,
    ),
    CompareCase(
        "pikachu-six",
        "Build a balanced team of 6 around Pikachu.",
        team_size=6,
        must_include=("pikachu",),
        max_vulnerabilities=0,
    ),
    CompareCase(
        "gengar-fact",
        "Is Gengar weak to Psychic-type moves?",
        must_match=(r"\byes\b", r"2\s*[×x]|super[- ]effective|double"),
    ),
)


@dataclass(frozen=True, slots=True)
class RunOutcome:
    case: CompareCase
    system: str
    failures: tuple[str, ...]
    tokens: int
    latency_ms: int
    answer: str = ""
    analysis: TeamAnalysis | None = None

    @property
    def passed(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict[str, Any]:
        return {
            "case": self.case.id,
            "system": self.system,
            "passed": self.passed,
            "failures": list(self.failures),
            "tokens": self.tokens,
            "latency_ms": self.latency_ms,
            "team": list(self.analysis.team.names) if self.analysis else [],
            "score": list(self.analysis.score) if self.analysis else None,
        }


def observed_team(result: SupervisorResult) -> list[str]:
    """The team the specialists actually produced: optimizer's final, else the builder's."""
    team: list[str] = []
    for delegation in result.delegations:
        if delegation.output is None:
            continue
        if delegation.agent == "team_optimizer":
            team = list(delegation.output["final_members"])
        elif delegation.agent == "team_builder":
            team = [member["name"] for member in delegation.output["members"]]
    return team


def mentions(answer: str, name: str) -> bool:
    text = answer.lower()
    return name in text or name.replace("-", " ") in text


def check(
    case: CompareCase, answer: str, team: Team | None, analysis: TeamAnalysis | None
) -> tuple[str, ...]:
    failures = [
        f"answer does not match {pattern!r}"
        for pattern in case.must_match
        if not re.search(pattern, answer, re.IGNORECASE)
    ]
    if case.team_size is None:
        return tuple(failures)
    if team is None or analysis is None:
        return (*failures, "no team produced")
    names = team.names
    if len(names) != case.team_size:
        failures.append(f"team has {len(names)} members, expected {case.team_size}")
    missing = [name for name in case.must_include if name not in names]
    if missing:
        failures.append(f"team is missing {missing}")
    if case.only_types:
        off = [m.name for m in team.members if not set(m.types) & case.only_types]
        if off:
            failures.append(f"members outside the allowed types: {off}")
    for attacking in case.must_cover:
        if all(effectiveness(attacking, m.types) >= 1 for m in team.members):
            failures.append(f"nobody resists {attacking.value}")
    vulnerabilities = len(analysis.vulnerabilities)
    if case.max_vulnerabilities is not None and vulnerabilities > case.max_vulnerabilities:
        failures.append(f"{vulnerabilities} vulnerabilities > {case.max_vulnerabilities}")
    unnamed = sorted({name for name in names if not mentions(answer, name)})
    if unnamed:
        failures.append(f"answer does not name team members {unnamed}")
    return tuple(failures)


def _resolve(catalog: PokemonCatalog, names: list[str]) -> Team | str:
    if not names:
        return "no team produced"
    try:
        return Team(tuple(catalog.get(normalize_pokemon_identifier(n)) for n in names))
    except (PokemonNotInCatalogError, ValueError) as error:
        return f"invalid team {names}: {error}"


def run_case(
    system: str, case: CompareCase, chat: ChatModel, catalog: PokemonCatalog
) -> RunOutcome:
    """Run one case on one system. Model misbehaviour fails the run; outages propagate."""
    runners: dict[str, Callable[[], tuple[str, list[str], int, tuple[str, ...]]]] = {
        "single": lambda: _single(chat, catalog, case.request),
        "multi": lambda: _multi(chat, catalog, case.request, optimize=False),
        "multi+opt": lambda: _multi(chat, catalog, case.request, optimize=True),
    }
    started = time.perf_counter()
    try:
        answer, names, tokens, errors = runners[system]()
    except LlmRequestError as error:
        tokens = error.completion.total_tokens if error.completion else 0
        latency = round((time.perf_counter() - started) * 1000)
        return RunOutcome(case, system, (f"request error: {error}",), tokens, latency)
    latency = round((time.perf_counter() - started) * 1000)

    team = None
    analysis = None
    failures: tuple[str, ...] = ()
    if case.team_size is not None:
        resolved = _resolve(catalog, names)
        if isinstance(resolved, str):
            failures = (resolved,)
        else:
            team, analysis = resolved, analyze_team(resolved)
    failures = (*failures, *check(case, answer, team, analysis))
    # Specialist errors the supervisor recovered from are not failures; they explain ones.
    if failures:
        failures = (*errors, *failures)
    return RunOutcome(
        case, system, tuple(dict.fromkeys(failures)), tokens, latency, answer, analysis
    )


def _single(
    chat: ChatModel, catalog: PokemonCatalog, request: str
) -> tuple[str, list[str], int, tuple[str, ...]]:
    result = GeneralistAgent(chat, catalog).run(request)
    return result.answer, list(result.team), result.completion.total_tokens, ()


def _multi(
    chat: ChatModel, catalog: PokemonCatalog, request: str, *, optimize: bool
) -> tuple[str, list[str], int, tuple[str, ...]]:
    result = Supervisor(chat, catalog, optimize=optimize).run(request)
    errors = tuple(f"{d.agent} failed: {d.error}" for d in result.delegations if d.error)
    return result.answer, observed_team(result), result.total_tokens, errors
