from typing import Any

import pytest

from pokeverse.agents import Confidence, PokedexAnswer, ResearchResult
from pokeverse.evals import RESEARCH_CASES, EvalCase, check, run_case
from pokeverse.evals.research import ALL_TYPES
from pokeverse.llm import Completion, LlmRequestError, ToolCall

CASE = EvalCase("pikachu-type", "What type is Pikachu?", frozenset({"pikachu"}), ("electric",))
LOOKUP = ToolCall("get_pokemon", {"name_or_id": "pikachu"}, {"name": "pikachu"})


def result(
    text: str = "Pikachu is Electric-type.",
    pokemon: tuple[str, ...] = ("pikachu",),
    confidence: Confidence = Confidence.HIGH,
    tool_calls: tuple[ToolCall, ...] = (LOOKUP,),
) -> ResearchResult:
    completion = Completion("", "fake", "completed", 10, 5, 7, tool_calls)
    return ResearchResult(
        answer=PokedexAnswer(answer=text, pokemon=pokemon, confidence=confidence),
        completion=completion,
    )


def test_correct_result_passes() -> None:
    assert check(CASE, result()) == ()


@pytest.mark.parametrize(
    ("kwargs", "failure"),
    [
        ({"tool_calls": ()}, "expected lookup=True"),
        ({"pokemon": ("raichu",)}, "pokemon ['raichu']"),
        ({"text": "Pikachu is a mouse."}, "does not mention ['electric']"),
    ],
)
def test_check_reports_failures(kwargs: dict[str, Any], failure: str) -> None:
    failures = check(CASE, result(**kwargs))

    assert any(failure in message for message in failures)


def test_unverified_claim_is_reported_as_ungrounded() -> None:
    failures = check(CASE, result(tool_calls=()))

    assert "ungrounded pokemon ['pikachu']" in failures


@pytest.mark.parametrize(
    ("text", "failures"),
    [
        ("Missingno is not in the catalog, so I cannot say.", ()),
        ("I did not notice it in the catalog.", ()),  # "ice" only as part of a word
        ("Missingno is a Bird/Normal type.", ("answer mentions ['normal']",)),
    ],
)
def test_must_not_mention_catches_invented_facts(text: str, failures: tuple[str, ...]) -> None:
    case = EvalCase("unknown", "What type is Missingno?", frozenset(), must_not_mention=ALL_TYPES)

    assert check(case, result(pokemon=(), text=text)) == failures


def test_unexpected_lookup_fails_off_topic_case() -> None:
    case = EvalCase("off-topic", "Capital of France?", frozenset(), expect_lookup=False)

    failures = check(case, result(pokemon=(), text="Paris."))

    assert failures == ("expected lookup=False, got True",)


class FailingAgent:
    def ask(self, question: str) -> ResearchResult:
        raise LlmRequestError("Model reply failed validation: bad slug")


def test_request_errors_fail_the_case_instead_of_aborting() -> None:
    outcome = run_case(FailingAgent(), CASE)  # type: ignore[arg-type]

    assert not outcome.passed
    assert not outcome.tool_use_correct
    assert "bad slug" in outcome.failures[0]


def test_required_tool_must_be_called() -> None:
    case = EvalCase(
        "weak", "Is Pikachu weak to Ground?", frozenset({"pikachu"}),
        required_tools=("get_type_matchups",),
    )  # fmt: skip

    failures = check(case, result())

    assert failures == ("did not call ['get_type_matchups']",)


def test_case_ids_are_unique() -> None:
    ids = [case.id for case in RESEARCH_CASES]

    assert len(ids) == len(set(ids))
