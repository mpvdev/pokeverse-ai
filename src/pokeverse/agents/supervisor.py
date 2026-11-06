"""The Supervisor Agent: routes a request to specialist agents exposed as tools."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

from pokeverse.agents.context import SharedContext, with_context
from pokeverse.agents.optimizer import TeamOptimizationAgent
from pokeverse.agents.research import ChatModel, ResearchAgent
from pokeverse.agents.team_builder import TeamCompositionAgent
from pokeverse.agents.tools import normalize_pokemon_identifier
from pokeverse.catalog import PokemonCatalog, PokemonNotInCatalogError
from pokeverse.llm import Completion, LlmRequestError, Tool
from pokeverse.teams import MAX_TEAM_SIZE, Team

OptimizeMode = Literal["never", "auto", "always"]
OPTIMIZE_MODES: tuple[str, ...] = get_args(OptimizeMode)

OPTIMIZER_INSTRUCTIONS: dict[str, str] = {
    "never": "",
    "auto": (
        "When the team ask_team_builder builds has vulnerabilities, the Team Optimization "
        "Agent automatically tries to improve it and the result includes `optimization`; if it "
        "has `final_members`, present that final team, mention accepted swaps and correct any "
        "claims it marked wrong. Use ask_team_optimizer only when the user asks to improve a "
        "team they already have. "
    ),
    "always": (
        "Use ask_team_optimizer to review and improve a team: after ask_team_builder returns a "
        "team, call it with the member names, the user's goal, the Pokémon the user explicitly "
        "required under `keep`, and the builder's member roles and summary as `notes`; also use "
        "it when the user asks to improve a team they already have. Present the optimizer's "
        "final team, mention accepted swaps, and correct any claims it found to be wrong. "
    ),
}


def supervisor_prompt(optimize: OptimizeMode) -> str:
    return (
        "You are the PokéVerse Supervisor. You coordinate specialist agents and never answer "
        "Pokémon facts or build teams yourself. "
        "Use ask_research_agent for facts about specific Pokémon: types, Pokédex numbers, "
        "weaknesses, resistances and type matchups. "
        "Use ask_team_builder to build or propose a team, passing the Pokémon the user "
        "explicitly required as `keep`. "
        + OPTIMIZER_INSTRUCTIONS[optimize]
        + "Specialists cannot see the user's message: give each one a complete, self-contained "
        "task with every constraint the user stated, and do not add requirements the user did "
        "not ask for. If a request needs both, call both, and split it: give the Research Agent "
        "only the factual question and the Team Composition Agent only the team request. Facts "
        "found by one specialist are passed to the next automatically, so you do not need to "
        "repeat them. "
        "Base your final answer only on specialist results; if a specialist reports an error, "
        "ungrounded claims or a team it did not check, say so. "
        "If the request is not about Pokémon, briefly say what PokéVerse can help with and do "
        "not call a specialist. Answer concisely in plain text."
    )


SUPERVISOR_SYSTEM_PROMPT = supervisor_prompt("auto")
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

BUILDER_PARAMETERS = {
    "type": "object",
    "properties": {
        **TASK_PARAMETERS["properties"],
        "keep": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Pokémon the user explicitly required; never swapped out.",
        },
    },
    "required": ["task", "keep"],
    "additionalProperties": False,
}

OPTIMIZER_PARAMETERS = {
    "type": "object",
    "properties": {
        "members": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": MAX_TEAM_SIZE,
            "description": "The team's member names.",
        },
        "goal": {"type": "string", "description": "What the user wants from the team."},
        "keep": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Members the user explicitly required; they will not be swapped out.",
        },
        "notes": {
            "type": "string",
            "description": "The team author's roles and summary, to fact-check.",
        },
    },
    "required": ["members", "goal", "keep", "notes"],
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
    # Pokémon whose verified facts were handed to this specialist with its task.
    handoff: tuple[str, ...] = ()

    @property
    def tokens(self) -> int:
        return self.completion.total_tokens if self.completion else 0

    def to_dict(self) -> dict[str, Any]:
        result = {"output": self.output} if self.error is None else {"error": self.error}
        return {
            "agent": self.agent,
            "task": self.task,
            "handoff": list(self.handoff),
            **result,
            "tokens": self.tokens,
        }


@dataclass(frozen=True, slots=True)
class SupervisorResult:
    answer: str
    delegations: tuple[Delegation, ...]
    completion: Completion
    context: SharedContext = field(default_factory=SharedContext)

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
            "context": self.context.to_dict(),
            "usage": {
                "supervisor_tokens": self.completion.total_tokens,
                "specialist_tokens": self.specialist_tokens,
                "total_tokens": self.total_tokens,
            },
        }


class Supervisor:
    """Delegates to the Research, Team Composition and Team Optimization agents.

    ``optimize`` controls the optimizer: ``never``; ``auto`` (code runs it after a build only
    when the team has vulnerabilities); or ``always`` (the supervisor is told to run it).
    """

    def __init__(
        self, chat: ChatModel, catalog: PokemonCatalog, *, optimize: OptimizeMode = "auto"
    ) -> None:
        if optimize not in OPTIMIZE_MODES:
            raise ValueError(f"optimize must be one of {', '.join(OPTIMIZE_MODES)}")
        self._chat = chat
        self._catalog = catalog
        self._mode: OptimizeMode = optimize
        self._research = ResearchAgent(chat, catalog)
        self._team_builder = TeamCompositionAgent(chat, catalog)
        self._optimizer = TeamOptimizationAgent(chat, catalog)

    def _optimize(
        self, members: list[str], goal: str, keep: list[str], notes: str, context: SharedContext
    ) -> Any:
        try:
            team = Team(
                tuple(self._catalog.get(normalize_pokemon_identifier(name)) for name in members)
            )
        except PokemonNotInCatalogError as error:
            raise ValueError(f"cannot optimize: {error}") from error
        return self._optimizer.optimize(
            team, goal=goal, keep=keep, notes=notes, facts=context.render()
        )

    def run(self, request: str) -> SupervisorResult:
        delegations: list[Delegation] = []
        context = SharedContext()

        def delegate(agent: str, task: str, work: Callable[[SharedContext], Any]) -> dict[str, Any]:
            handoff = context.names
            try:
                result = work(context)
            except LlmRequestError as error:
                delegations.append(
                    Delegation(
                        agent, task, error=str(error), completion=error.completion, handoff=handoff
                    )
                )
                return {"error": "specialist_failed", "message": str(error)}
            except ValueError as error:
                delegations.append(Delegation(agent, task, error=str(error), handoff=handoff))
                return {"error": "specialist_failed", "message": str(error)}
            context.record(result.completion.tool_calls)
            output = result.to_dict()
            delegations.append(
                Delegation(agent, task, output, completion=result.completion, handoff=handoff)
            )
            return output

        def build_team(task: str, keep: list[str]) -> dict[str, Any]:
            output = delegate(
                "team_builder", task, lambda ctx: self._team_builder.build(with_context(task, ctx))
            )
            if self._mode != "auto" or "error" in output:
                return output
            if not output["analysis"]["vulnerabilities"]:
                return {**output, "optimization": {"skipped": "the team has no vulnerabilities"}}
            members = [member["name"] for member in output["members"]]
            roles = "\n".join(f"{m['name']}: {m['role']}" for m in output["members"])
            notes = f"{roles}\n{output['summary']}"
            optimization = delegate(
                "team_optimizer",
                f"auto-optimize {members} (keep: {keep or 'none'})",
                lambda ctx: self._optimize(members, task, keep, notes, ctx),
            )
            return {**output, "optimization": optimization}

        tools = (
            Tool(
                name="ask_research_agent",
                description=(
                    "Ask the Research Agent a factual question about specific Pokémon. Returns "
                    "`answer`, `pokemon`, `confidence` and `ungrounded` (claims it could not "
                    "verify), or an error object."
                ),
                parameters=TASK_PARAMETERS,
                handler=lambda task: delegate(
                    "research",
                    task,
                    lambda ctx: self._research.ask(
                        with_context(task, ctx), verified=frozenset(ctx.names)
                    ),
                ),
            ),
            Tool(
                name="ask_team_builder",
                description=(
                    "Ask the Team Composition Agent to build a team. Returns `members` with "
                    "roles, its `summary`, a deterministic `analysis` (vulnerabilities, "
                    "unresisted types, offensive gaps) and `self_checked`, or an error object."
                    + (
                        " Also returns `optimization`: the optimizer's result when the team had "
                        "vulnerabilities, otherwise why it was skipped."
                        if self._mode == "auto"
                        else ""
                    )
                ),
                parameters=BUILDER_PARAMETERS,
                handler=build_team,
            ),
            Tool(
                name="ask_team_optimizer",
                description=(
                    "Ask the Team Optimization Agent to review a team. It fact-checks type "
                    "claims in `notes` against the type chart and proposes swaps; only swaps "
                    "that measurably improve the deterministic analysis are kept. Returns "
                    "`final_members`, `final_analysis`, `swaps` (accepted or rejected, with "
                    "verdicts), `claims` (with `correct`) and `critique`, or an error object."
                ),
                parameters=OPTIMIZER_PARAMETERS,
                handler=lambda members, goal, keep, notes: delegate(
                    "team_optimizer",
                    f"optimize {members} (goal: {goal or 'none'}; keep: {keep or 'none'})",
                    lambda ctx: self._optimize(members, goal, keep, notes, ctx),
                ),
            ),
        )
        if self._mode == "never":
            tools = tools[:2]
        completion = self._chat.complete(
            request,
            system=supervisor_prompt(self._mode),
            max_tokens=SUPERVISOR_MAX_TOKENS,
            tools=tools,
        )
        if not completion.text.strip():
            raise LlmRequestError("Supervisor returned an empty answer")
        return SupervisorResult(completion.text, tuple(delegations), completion, context)
