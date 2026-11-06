from collections.abc import Iterator
from typing import Any

import pytest

from pokeverse.agents import RESEARCH_SYSTEM_PROMPT, Supervisor
from pokeverse.agents.supervisor import SUPERVISOR_SYSTEM_PROMPT
from pokeverse.agents.team_builder import TEAM_BUILDER_SYSTEM_PROMPT
from pokeverse.catalog import Pokemon, PokemonCatalog, PokemonType, SqlitePokemonRepository
from pokeverse.llm import Completion, LlmRequestError, ToolCall

PIKACHU = Pokemon(25, "pikachu", (PokemonType.ELECTRIC,))
GOOD_ANSWER = {"answer": "Pikachu is Electric-type.", "pokemon": ["pikachu"], "confidence": "high"}
TEAM = {"members": [{"name": "pikachu", "role": "lead"}], "summary": "Just Pikachu."}


class RoutingChat:
    """Plays every agent: the supervisor follows a script; specialists return canned output."""

    def __init__(
        self,
        delegate_to: list[tuple[str, str]],
        answer: str = "Final answer.",
        research: dict[str, Any] = GOOD_ANSWER,
    ) -> None:
        self.delegate_to = delegate_to
        self.answer = answer
        self.research = research
        self.prompts: list[tuple[str, str]] = []

    def complete(self, prompt: str, **kwargs: Any) -> Completion:
        system = kwargs["system"]
        self.prompts.append((system, prompt))
        if system == SUPERVISOR_SYSTEM_PROMPT:
            tools = {tool.name: tool for tool in kwargs["tools"]}
            calls = tuple(
                ToolCall(name, {"task": task}, tools[name].handler(task=task))
                for name, task in self.delegate_to
            )
            return Completion(self.answer, "fake", "completed", 100, 20, 9, calls)
        if system == RESEARCH_SYSTEM_PROMPT:
            lookup = ToolCall("get_pokemon", {"name_or_id": "pikachu"}, PIKACHU.to_dict())
            return Completion("", "fake", "completed", 30, 10, 5, (lookup,), self.research)
        assert system == TEAM_BUILDER_SYSTEM_PROMPT
        analyzed = ToolCall(
            "analyze_team", {"names": ["pikachu"]}, {"team": {"members": [PIKACHU.to_dict()]}}
        )
        return Completion("", "fake", "completed", 200, 50, 5, (analyzed,), TEAM)


@pytest.fixture
def catalog() -> Iterator[PokemonCatalog]:
    with SqlitePokemonRepository(":memory:") as repository:
        repository.save(PIKACHU)
        yield PokemonCatalog(repository)


def test_supervisor_exposes_specialists_as_tools(catalog: PokemonCatalog) -> None:
    chat = RoutingChat([])

    Supervisor(chat, catalog).run("Hi")

    assert chat.prompts == [(SUPERVISOR_SYSTEM_PROMPT, "Hi")]


def test_research_question_is_delegated(catalog: PokemonCatalog) -> None:
    chat = RoutingChat([("ask_research_agent", "What type is Pikachu?")])

    result = Supervisor(chat, catalog).run("What type is Pikachu?")

    assert result.answer == "Final answer."
    (delegation,) = result.delegations
    assert delegation.agent == "research"
    assert delegation.task == "What type is Pikachu?"
    assert delegation.output == {**GOOD_ANSWER, "ungrounded": []}
    assert chat.prompts[1] == (RESEARCH_SYSTEM_PROMPT, "What type is Pikachu?")


def test_both_specialists_and_token_accounting(catalog: PokemonCatalog) -> None:
    chat = RoutingChat(
        [("ask_research_agent", "Pikachu's type?"), ("ask_team_builder", "Team around Pikachu")]
    )

    result = Supervisor(chat, catalog).run("Tell me about Pikachu and build a team")

    assert [d.agent for d in result.delegations] == ["research", "team_builder"]
    assert result.delegations[1].output["self_checked"] is True
    assert result.specialist_tokens == 40 + 250
    assert result.total_tokens == 120 + 290
    assert result.to_dict()["usage"] == {
        "supervisor_tokens": 120,
        "specialist_tokens": 290,
        "total_tokens": 410,
    }


def test_verified_facts_are_handed_to_the_next_specialist(catalog: PokemonCatalog) -> None:
    chat = RoutingChat(
        [("ask_research_agent", "Pikachu's type?"), ("ask_team_builder", "Team around Pikachu")]
    )

    result = Supervisor(chat, catalog).run("q")

    research, team_builder = result.delegations
    assert research.handoff == ()
    assert team_builder.handoff == ("pikachu",)
    assert team_builder.task == "Team around Pikachu"
    team_prompt = chat.prompts[2][1]
    assert team_prompt.startswith("Team around Pikachu\n\nVerified facts")
    assert "- pikachu (#25): electric" in team_prompt
    assert result.to_dict()["context"]["pokemon"] == [PIKACHU.to_dict()]


def test_handed_over_facts_count_as_grounded(catalog: PokemonCatalog) -> None:
    class NoLookupResearchChat(RoutingChat):
        def complete(self, prompt: str, **kwargs: Any) -> Completion:
            completion = super().complete(prompt, **kwargs)
            if kwargs["system"] == RESEARCH_SYSTEM_PROMPT and len(self.prompts) > 2:
                return Completion("", "fake", "completed", 30, 10, 5, (), GOOD_ANSWER)
            return completion

    chat = NoLookupResearchChat([("ask_research_agent", "a"), ("ask_research_agent", "b")])

    result = Supervisor(chat, catalog).run("q")

    second = result.delegations[1]
    assert second.handoff == ("pikachu",)
    assert second.completion is not None and second.completion.tool_calls == ()
    assert second.output is not None and second.output["ungrounded"] == []


def test_specialist_failure_is_returned_to_supervisor_as_data(catalog: PokemonCatalog) -> None:
    bad = {"answer": "x", "pokemon": ["Not A Slug"], "confidence": "high"}
    chat = RoutingChat([("ask_research_agent", "q")], research=bad)

    result = Supervisor(chat, catalog).run("q")

    (delegation,) = result.delegations
    assert delegation.output is None
    assert "failed validation" in delegation.error
    assert delegation.to_dict()["error"] == delegation.error
    assert delegation.tokens == 40


def test_empty_supervisor_answer_raises(catalog: PokemonCatalog) -> None:
    with pytest.raises(LlmRequestError, match="empty answer"):
        Supervisor(RoutingChat([], answer="  "), catalog).run("q")
