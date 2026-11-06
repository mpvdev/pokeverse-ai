"""The Supervisor Agent: routes a request to specialist agents exposed as tools."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pokeverse.agents.research import ChatModel, ResearchAgent
from pokeverse.agents.team_builder import TeamCompositionAgent
from pokeverse.catalog import PokemonCatalog
from pokeverse.llm import Completion, LlmRequestError, Tool

SUPERVISOR_SYSTEM_PROMPT = (
    "You are the PokéVerse Supervisor. You coordinate specialist agents and never answer "
    "Pokémon facts or build teams yourself. "
    "Use ask_research_agent for facts about specific Pokémon: types, Pokédex numbers, "
    "weaknesses, resistances and type matchups. "
    "Use ask_team_builder to build or propose a team. "
    "Specialists cannot see the user's message: give each one a complete, self-contained task "
    "with every constraint the user stated. If a request needs both, call both. "
    "Base your final answer only on specialist results; if a specialist reports an error, "
    "ungrounded claims or a team it did not check, say so. "
    "If the request is not about Pokémon, briefly say what PokéVerse can help with and do not "
    "call a specialist. Answer concisely in plain text."
)
SUPERVISOR_MAX_TOKENS = 1000

TASK_PARAMETERS = {
    "type": "object",
    "properties": {
        "task": {
            "type": "string",
            "description": "A complete, self-contained task including all user constraints.",
        }
    },
    "required": ["task"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class Delegation:
    """One task handed to a specialist, and what came back."""

    agent: str
    task: str
    output: dict[str, Any] | None = None
    error: str | None = None
    completion: Completion | None = None

    @property
    def tokens(self) -> int:
        return self.completion.total_tokens if self.completion else 0

    def to_dict(self) -> dict[str, Any]:
        result = {"output": self.output} if self.error is None else {"error": self.error}
        return {"agent": self.agent, "task": self.task, **result, "tokens": self.tokens}


@dataclass(frozen=True, slots=True)
class SupervisorResult:
    answer: str
    delegations: tuple[Delegation, ...]
    completion: Completion

    @property
    def specialist_tokens(self) -> int:
        return sum(delegation.tokens for delegation in self.delegations)

    @property
    def total_tokens(self) -> int:
        return self.completion.total_tokens + self.specialist_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "delegations": [delegation.to_dict() for delegation in self.delegations],
            "usage": {
                "supervisor_tokens": self.completion.total_tokens,
                "specialist_tokens": self.specialist_tokens,
                "total_tokens": self.total_tokens,
            },
        }


class Supervisor:
    """Delegates to the Research and Team Composition agents and composes their results."""

    def __init__(self, chat: ChatModel, catalog: PokemonCatalog) -> None:
        self._chat = chat
        self._research = ResearchAgent(chat, catalog)
        self._team_builder = TeamCompositionAgent(chat, catalog)

    def run(self, request: str) -> SupervisorResult:
        delegations: list[Delegation] = []

        def delegate(agent: str, task: str, work: Callable[[], Any]) -> dict[str, Any]:
            try:
                result = work()
            except (LlmRequestError, ValueError) as error:
                delegations.append(Delegation(agent, task, error=str(error)))
                return {"error": "specialist_failed", "message": str(error)}
            output = result.to_dict()
            delegations.append(Delegation(agent, task, output, completion=result.completion))
            return output

        tools = (
            Tool(
                name="ask_research_agent",
                description=(
                    "Ask the Research Agent a factual question about specific Pokémon. Returns "
                    "`answer`, `pokemon`, `confidence` and `ungrounded` (claims it could not "
                    "verify), or an error object."
                ),
                parameters=TASK_PARAMETERS,
                handler=lambda task: delegate("research", task, lambda: self._research.ask(task)),
            ),
            Tool(
                name="ask_team_builder",
                description=(
                    "Ask the Team Composition Agent to build a team. Returns `members` with "
                    "roles, its `summary`, a deterministic `analysis` (vulnerabilities, "
                    "unresisted types, offensive gaps) and `self_checked`, or an error object."
                ),
                parameters=TASK_PARAMETERS,
                handler=lambda task: delegate(
                    "team_builder", task, lambda: self._team_builder.build(task)
                ),
            ),
        )
        completion = self._chat.complete(
            request,
            system=SUPERVISOR_SYSTEM_PROMPT,
            max_tokens=SUPERVISOR_MAX_TOKENS,
            tools=tools,
        )
        if not completion.text.strip():
            raise LlmRequestError("Supervisor returned an empty answer")
        return SupervisorResult(completion.text, tuple(delegations), completion)
