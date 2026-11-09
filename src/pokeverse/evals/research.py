"""Evaluation of the Research Agent against a fixed set of questions."""

import re
import time
from collections.abc import Iterable
from dataclasses import dataclass

from pokeverse.agents.research import ResearchAgent, ResearchResult
from pokeverse.catalog import PokemonType
from pokeverse.llm import LlmRequestError

ALL_TYPES = tuple(member.value for member in PokemonType)


@dataclass(frozen=True, slots=True)
class EvalCase:
    id: str
    question: str
    expected_pokemon: frozenset[str]
    must_mention: tuple[str, ...] = ()
    # True: the agent must call a tool; False: it must not.
    expect_lookup: bool = True
    required_tools: tuple[str, ...] = ()
    # Whole words that would indicate an invented fact.
    must_not_mention: tuple[str, ...] = ()


RESEARCH_CASES: tuple[EvalCase, ...] = (
    EvalCase("pikachu-type", "What type is Pikachu?", frozenset({"pikachu"}), ("electric",)),
    EvalCase(
        "charizard-types",
        "What are Charizard's types?",
        frozenset({"charizard"}),
        ("fire", "flying"),
    ),
    EvalCase(
        "mr-mime-number",
        "What is Mr. Mime's National Pokédex number?",
        frozenset({"mr-mime"}),
        ("122",),
    ),
    EvalCase("by-number", "Which Pokémon is number 25?", frozenset({"pikachu"}), ("pikachu",)),
    EvalCase(
        "compare",
        "Which of Blastoise and Charizard is Water-type?",
        frozenset({"blastoise", "charizard"}),
        ("blastoise",),
    ),
    EvalCase(
        "unknown-pokemon",
        "What type is Missingno?",
        frozenset(),
        must_not_mention=ALL_TYPES,
    ),
    EvalCase(
        "off-topic",
        "What is the capital of France?",
        frozenset(),
        expect_lookup=False,
    ),
    EvalCase(
        "gengar-vs-psychic",
        "Is Gengar weak to Psychic-type moves?",
        frozenset({"gengar"}),
        ("psychic",),
        required_tools=("get_type_matchups",),
    ),
    EvalCase(
        "gengar-weaknesses",
        "List all of Gengar's weaknesses.",
        frozenset({"gengar"}),
        ("ground", "psychic", "ghost", "dark"),
        required_tools=("get_type_matchups",),
    ),
    EvalCase(
        "electric-vs-garchomp",
        "Can Electric-type moves hurt Garchomp?",
        frozenset({"garchomp"}),
        ("immune",),
        required_tools=("get_type_matchups",),
    ),
)


@dataclass(frozen=True, slots=True)
class EvalResult:
    case: EvalCase
    failures: tuple[str, ...]
    latency_ms: int
    result: ResearchResult | None = None

    @property
    def passed(self) -> bool:
        return not self.failures

    @property
    def tool_use_correct(self) -> bool:
        return self.result is not None and (
            bool(self.result.completion.tool_calls) == self.case.expect_lookup
        )


def check(case: EvalCase, result: ResearchResult) -> tuple[str, ...]:
    """Deterministic checks of one agent result; returns failure descriptions."""
    failures = []
    called = bool(result.completion.tool_calls)
    if called != case.expect_lookup:
        failures.append(f"expected lookup={case.expect_lookup}, got {called}")
    used = {call.name for call in result.completion.tool_calls}
    unused = [tool for tool in case.required_tools if tool not in used]
    if unused:
        failures.append(f"did not call {unused}")
    if set(result.answer.pokemon) != case.expected_pokemon:
        failures.append(
            f"pokemon {sorted(result.answer.pokemon)} != expected {sorted(case.expected_pokemon)}"
        )
    text = result.answer.answer.lower()
    missing = [fact for fact in case.must_mention if fact.lower() not in text]
    if missing:
        failures.append(f"answer does not mention {missing}")
    if result.ungrounded:
        failures.append(f"ungrounded pokemon {list(result.ungrounded)}")
    invented = [word for word in case.must_not_mention if re.search(rf"\b{word}\b", text)]
    if invented:
        failures.append(f"answer mentions {invented}")
    return tuple(failures)


def run_case(agent: ResearchAgent, case: EvalCase) -> EvalResult:
    """Run one case. Model misbehaviour fails the case; auth/outage errors propagate."""
    started = time.perf_counter()
    try:
        result = agent.ask(case.question)
    except LlmRequestError as error:
        latency = round((time.perf_counter() - started) * 1000)
        return EvalResult(case, (f"request error: {error}",), latency)
    latency = round((time.perf_counter() - started) * 1000)
    return EvalResult(case, check(case, result), latency, result)


def evaluate(agent: ResearchAgent, cases: Iterable[EvalCase]) -> list[EvalResult]:
    return [run_case(agent, case) for case in cases]
