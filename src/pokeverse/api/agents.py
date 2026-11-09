"""Agent endpoints: one synchronous request per agent run (seconds to about a minute)."""

from typing import Any

from fastapi import APIRouter
from pydantic import Field

from pokeverse.agents import (
    OpponentAnalysis,
    OpponentAnalysisAgent,
    OptimizationResult,
    ResearchAgent,
    ResearchResult,
    Supervisor,
    SupervisorResult,
    TeamBuildResult,
    TeamCompositionAgent,
    TeamOptimizationAgent,
)
from pokeverse.agents.supervisor import OptimizeMode
from pokeverse.api.app import Catalogs, Chat, Name, NameOrId, invalid_input
from pokeverse.api.battles import TeamSpec, resolve_battler
from pokeverse.llm import Completion
from pokeverse.model import FrozenModel, NonBlank
from pokeverse.teams import MAX_TEAM_SIZE, Team

router = APIRouter(tags=["agents"])

MAX_PROMPT = 2000


class ToolUse(FrozenModel):
    name: str
    arguments: dict[str, Any]


class Usage(FrozenModel):
    """Observed cost of the agent's own LLM call (specialists are counted in the result)."""

    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: int
    tool_calls: tuple[ToolUse, ...]

    @classmethod
    def of(cls, completion: Completion) -> Usage:
        return cls(
            model=completion.model_id,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
            total_tokens=completion.total_tokens,
            latency_ms=completion.latency_ms,
            tool_calls=tuple(
                ToolUse(name=call.name, arguments=call.arguments) for call in completion.tool_calls
            ),
        )


class AgentResponse[T](FrozenModel):
    result: T
    usage: Usage


class Question(FrozenModel):
    question: NonBlank = Field(max_length=MAX_PROMPT, examples=["What type is Mr. Mime?"])


class BuildRequest(FrozenModel):
    request: NonBlank = Field(
        max_length=MAX_PROMPT, examples=["A rain team with Pelipper and four Water-types."]
    )


class OptimizeRequest(FrozenModel):
    members: list[NameOrId] = Field(min_length=1, max_length=MAX_TEAM_SIZE)
    goal: str = Field(default="", max_length=MAX_PROMPT)
    keep: list[Name] = Field(default=[], max_length=MAX_TEAM_SIZE)
    notes: str = Field(default="", max_length=MAX_PROMPT, description="Claims to fact-check.")


class AdviseRequest(FrozenModel):
    request: NonBlank = Field(max_length=MAX_PROMPT)
    optimize: OptimizeMode = "auto"


class ScoutRequest(FrozenModel):
    side1: TeamSpec = Field(min_length=1, max_length=MAX_TEAM_SIZE, description="Our team.")
    side2: TeamSpec = Field(min_length=1, max_length=MAX_TEAM_SIZE, description="The opponent.")


class ScoutReport(FrozenModel):
    analysis: OpponentAnalysis
    briefing: str = Field(description="What the Battle Strategy Agent is handed at turn 1.")


@router.post("/research", response_model=AgentResponse[ResearchResult])
def research(request: Question, catalogs: Catalogs, chat: Chat) -> AgentResponse[ResearchResult]:
    """The Research Agent; `ungrounded` lists Pokémon it named but never looked up."""
    with catalogs() as catalog:
        result = ResearchAgent(chat, catalog).ask(request.question)
    return AgentResponse(result=result, usage=Usage.of(result.completion))


@router.post("/teams/build", response_model=AgentResponse[TeamBuildResult])
def build_team(
    request: BuildRequest, catalogs: Catalogs, chat: Chat
) -> AgentResponse[TeamBuildResult]:
    """The Team Composition Agent; the analysis is recomputed by our code, not the model's."""
    with catalogs() as catalog:
        result = TeamCompositionAgent(chat, catalog).build(request.request)
    return AgentResponse(result=result, usage=Usage.of(result.completion))


@router.post("/teams/optimize", response_model=AgentResponse[OptimizationResult])
def optimize_team(
    request: OptimizeRequest, catalogs: Catalogs, chat: Chat
) -> AgentResponse[OptimizationResult]:
    """The Team Optimization Agent: claims checked by the type chart, swaps kept only if better."""
    with catalogs() as catalog:
        members = tuple(catalog.get(name) for name in request.members)
        with invalid_input():
            team = Team(members=members)
        result = TeamOptimizationAgent(chat, catalog).optimize(
            team, goal=request.goal, keep=request.keep, notes=request.notes
        )
    return AgentResponse(result=result, usage=Usage.of(result.completion))


@router.post("/advise", response_model=AgentResponse[SupervisorResult])
def advise(
    request: AdviseRequest, catalogs: Catalogs, chat: Chat
) -> AgentResponse[SupervisorResult]:
    """The Supervisor; `usage` is its own call, the result holds the specialists' tokens."""
    with catalogs() as catalog:
        result = Supervisor(chat, catalog, optimize=request.optimize).run(request.request)
    return AgentResponse(result=result, usage=Usage.of(result.completion))


@router.post("/scout", response_model=AgentResponse[ScoutReport])
def scout(request: ScoutRequest, catalogs: Catalogs, chat: Chat) -> AgentResponse[ScoutReport]:
    """The Opponent Analysis Agent ranks side 2's threats to side 1; counters are verified."""
    with catalogs() as catalog, invalid_input():
        own = [resolve_battler(catalog, spec) for spec in request.side1]
        foe = [resolve_battler(catalog, spec) for spec in request.side2]
    analysis = OpponentAnalysisAgent(chat).analyze(own, foe)
    return AgentResponse(
        result=ScoutReport(analysis=analysis, briefing=analysis.briefing()),
        usage=Usage.of(analysis.completion),
    )
