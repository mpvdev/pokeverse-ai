"""Background jobs for long work: agent battles, multi-run battles and evaluation suites.

``POST /jobs/...`` validates the request, starts the work and answers 202 with the job;
``GET /jobs/{id}`` reports its status, progress and, once finished, its result or error.
Jobs live in memory: they are lost on restart, and nothing limits how many are kept.
"""

import random
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import Field

from pokeverse.agents import (
    BattleStrategyAgent,
    ChatModel,
    OpponentAnalysis,
    OpponentAnalysisAgent,
    ResearchAgent,
)
from pokeverse.api.app import Catalogs
from pokeverse.api.battles import BattlerSpec, TeamSpec, battler_spec, resolve_battler
from pokeverse.battles import Battler, Player, make_player, run_battle
from pokeverse.catalog import (
    MoveNotInCatalogError,
    PokemonCatalog,
    PokemonNotInCatalogError,
    UpstreamUnavailableError,
)
from pokeverse.evals import RESEARCH_CASES
from pokeverse.evals import run_case as research_case
from pokeverse.evals.battles import (
    BATTLE_SCENARIOS,
    BATTLE_SYSTEMS,
    LLM_SYSTEMS,
    BattleScenario,
    feedback_experiment,
    run_system,
)
from pokeverse.evals.compare import COMPARE_CASES, SYSTEMS
from pokeverse.evals.compare import run_case as compare_case
from pokeverse.llm import LlmAuthError, LlmRequestError, LlmUnavailableError
from pokeverse.model import FrozenModel
from pokeverse.teams import MAX_TEAM_SIZE

router = APIRouter(prefix="/jobs", tags=["jobs"])

MAX_RUNS = 1000
JobStatus = Literal["queued", "running", "succeeded", "failed"]
ErrorKind = Literal[
    "not_found",
    "invalid_input",
    "upstream_unavailable",
    "llm_unavailable",
    "llm_auth",
    "llm_request",
    "internal",
]
BattlePlayer = Literal["greedy", "random", "agent"]
ScenarioId = Literal[tuple(scenario.id for scenario in BATTLE_SCENARIOS)]
BattleSystem = Literal[BATTLE_SYSTEMS]
ResearchCaseId = Literal[tuple(case.id for case in RESEARCH_CASES)]
CompareCaseId = Literal[tuple(case.id for case in COMPARE_CASES)]
CompareSystem = Literal[SYSTEMS]


class JobError(FrozenModel):
    kind: ErrorKind
    message: str


class Job(FrozenModel):
    id: str
    kind: str
    status: JobStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: tuple[str, ...] = ()
    result: dict[str, Any] | None = None
    error: JobError | None = None


def classify(error: Exception) -> ErrorKind:
    """The same categories the synchronous endpoints map to HTTP status codes."""
    match error:
        case PokemonNotInCatalogError() | MoveNotInCatalogError():
            return "not_found"
        case UpstreamUnavailableError():
            return "upstream_unavailable"
        case LlmUnavailableError():
            return "llm_unavailable"
        case LlmAuthError():
            return "llm_auth"
        case LlmRequestError():
            return "llm_request"
        case ValueError():
            return "invalid_input"
        case _:
            return "internal"


type Work = Callable[[Callable[[str], None]], dict[str, Any]]


class JobStore:
    """Thread-safe, in-memory jobs; each change replaces the job with a new frozen snapshot."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = Lock()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _update(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            self._jobs[job_id] = self._jobs[job_id].model_copy(update=changes)

    def _note(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            self._jobs[job_id] = job.model_copy(update={"progress": (*job.progress, message)})

    def start(self, kind: str, work: Work, runner: Callable[[Callable[[], None]], object]) -> Job:
        job = Job(id=uuid4().hex, kind=kind, status="queued", created_at=datetime.now(UTC))
        with self._lock:
            self._jobs[job.id] = job

        def execute() -> None:
            self._update(job.id, status="running", started_at=datetime.now(UTC))
            try:
                result = work(lambda message: self._note(job.id, message))
            except Exception as error:
                failure = JobError(kind=classify(error), message=str(error))
                self._update(job.id, status="failed", error=failure, finished_at=datetime.now(UTC))
                return
            self._update(job.id, status="succeeded", result=result, finished_at=datetime.now(UTC))

        runner(execute)
        return self.get(job.id) or job


def _start(request: Request, response: Response, kind: str, work: Work) -> Job:
    job = request.app.state.jobs.start(kind, work, request.app.state.runner)
    response.headers["Location"] = f"/jobs/{job.id}"
    return job


def _chat(request: Request, needed: bool) -> ChatModel | None:
    """Created when the job is submitted, so missing credentials fail the request, not the job."""
    return request.app.state.chats() if needed else None


@router.get("/{job_id}", response_model=Job)
def get_job(job_id: str, request: Request) -> Job:
    job = request.app.state.jobs.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no job {job_id!r}")
    return job


class BattleJobRequest(FrozenModel):
    side1: TeamSpec = Field(min_length=1, max_length=MAX_TEAM_SIZE)
    side2: TeamSpec = Field(min_length=1, max_length=MAX_TEAM_SIZE)
    player1: BattlePlayer = "greedy"
    player2: BattlePlayer = "greedy"
    seed: int = 0
    runs: int = Field(default=1, ge=1, le=MAX_RUNS, description="Seeds seed, seed+1, ...")
    analysis: bool = Field(default=True, description="Brief agent players with a scouting run.")
    events: bool = Field(default=True, description="Include every battle's event log.")


def _battle_player(
    name: BattlePlayer, seed: str, chat: ChatModel | None, analysis: OpponentAnalysis | None
) -> Player:
    if name == "agent" and chat is not None:
        return BattleStrategyAgent(chat, analysis=analysis)
    return make_player(name, random.Random(seed))


@router.post("/battles", response_model=Job, status_code=status.HTTP_202_ACCEPTED)
def battle_job(
    body: BattleJobRequest, request: Request, response: Response, catalogs: Catalogs
) -> Job:
    """Battles with any players, including the Battle Strategy Agent; wins summed over runs."""
    names = (body.player1, body.player2)
    chat = _chat(request, "agent" in names)

    def work(progress: Callable[[str], None]) -> dict[str, Any]:
        with catalogs() as catalog:
            teams = [
                [resolve_battler(catalog, spec) for spec in side]
                for side in (body.side1, body.side2)
            ]
        analyses: dict[int, OpponentAnalysis] = {}
        if chat is not None and body.analysis:
            for side, name in enumerate(names):
                if name == "agent":
                    analyses[side] = OpponentAnalysisAgent(chat).analyze(
                        teams[side], teams[1 - side]
                    )
                    progress(f"side {side + 1} scouted the opponent")
        battles = []
        for seed in range(body.seed, body.seed + body.runs):
            players = tuple(
                _battle_player(name, f"{seed}:{side + 1}", chat, analyses.get(side))
                for side, name in enumerate(names)
            )
            result = run_battle(teams[0], teams[1], (players[0], players[1]), random.Random(seed))
            agents = [p for p in players if isinstance(p, BattleStrategyAgent)]
            battles.append(
                {
                    "seed": seed,
                    "winner": result.winner,
                    "turns": result.turns,
                    "agent_tokens": sum(agent.total_tokens for agent in agents),
                    "fallbacks": sum(agent.fallbacks for agent in agents),
                    "decisions": [d.to_dict() for agent in agents for d in agent.decisions],
                    "events": [e.model_dump(mode="json") for e in result.events]
                    if body.events
                    else None,
                }
            )
            progress(f"seed {seed}: winner {result.winner}, {result.turns} turns")
        wins = [sum(1 for b in battles if b["winner"] == side) for side in (0, 1)]
        return {
            "players": list(names),
            "teams": [[battler_spec(b).model_dump(mode="json") for b in team] for team in teams],
            "wins": wins,
            "draws": body.runs - sum(wins),
            "average_turns": sum(b["turns"] for b in battles) / body.runs,
            "agent_tokens": sum(b["agent_tokens"] for b in battles),
            "analysis_tokens": sum(a.completion.total_tokens for a in analyses.values()),
            "fallbacks": sum(b["fallbacks"] for b in battles),
            "analyses": {str(side + 1): a.model_dump(mode="json") for side, a in analyses.items()},
            "battles": battles,
        }

    return _start(request, response, "battles", work)


def _scenario_teams(
    catalog: PokemonCatalog, scenario: BattleScenario
) -> tuple[list[Battler], list[Battler]]:
    return (
        [resolve_battler(catalog, BattlerSpec(pokemon=name)) for name in scenario.side1],
        [resolve_battler(catalog, BattlerSpec(pokemon=name)) for name in scenario.side2],
    )


SCENARIOS = {scenario.id: scenario for scenario in BATTLE_SCENARIOS}


class BattleEvalRequest(FrozenModel):
    scenarios: list[ScenarioId] = Field(default=list(SCENARIOS), min_length=1)
    systems: list[BattleSystem] = Field(default=list(BATTLE_SYSTEMS), min_length=1)
    seeds: int = Field(default=5, ge=1, le=MAX_RUNS, description="Battles per system.")
    seed_start: int = 0


@router.post("/battle-evals", response_model=Job, status_code=status.HTTP_202_ACCEPTED)
def battle_eval_job(
    body: BattleEvalRequest, request: Request, response: Response, catalogs: Catalogs
) -> Job:
    """Win rate (Wilson 95% interval), detected mistakes and tokens per system, against greedy."""
    chat = _chat(request, any(system in LLM_SYSTEMS for system in body.systems))
    seeds = range(body.seed_start, body.seed_start + body.seeds)

    def work(progress: Callable[[str], None]) -> dict[str, Any]:
        reports: dict[str, list[dict[str, Any]]] = {}
        for scenario_id in body.scenarios:
            with catalogs() as catalog:
                team, opponent = _scenario_teams(catalog, SCENARIOS[scenario_id])
            reports[scenario_id] = [
                run_system(
                    system,
                    team,
                    opponent,
                    seeds,
                    chat,
                    progress=lambda message, s=scenario_id: progress(f"[{s}] {message}"),
                ).to_dict()
                for system in body.systems
            ]
        return {"seeds": list(seeds), "scenarios": reports}

    return _start(request, response, "battle-evals", work)


class FeedbackRequest(FrozenModel):
    scenario: ScenarioId = "bulk"
    train: int = Field(default=5, ge=1, le=MAX_RUNS, description="Training battles.")
    test: int = Field(default=5, ge=1, le=MAX_RUNS, description="Test battles per system.")
    seed_start: int = 0


@router.post("/battle-feedback", response_model=Job, status_code=status.HTTP_202_ACCEPTED)
def battle_feedback_job(
    body: FeedbackRequest, request: Request, response: Response, catalogs: Catalogs
) -> Job:
    """Lessons from the agent's detected mistakes on training seeds, measured on new seeds."""
    chat = _chat(request, True)
    train = range(body.seed_start, body.seed_start + body.train)
    test = range(train.stop, train.stop + body.test)

    def work(progress: Callable[[str], None]) -> dict[str, Any]:
        with catalogs() as catalog:
            team, opponent = _scenario_teams(catalog, SCENARIOS[body.scenario])
        report = feedback_experiment(team, opponent, chat, train, test, progress=progress)
        return {"train_seeds": list(train), "test_seeds": list(test), **report.to_dict()}

    return _start(request, response, "battle-feedback", work)


class ResearchEvalRequest(FrozenModel):
    cases: list[ResearchCaseId] = Field(default=[case.id for case in RESEARCH_CASES], min_length=1)


@router.post("/research-evals", response_model=Job, status_code=status.HTTP_202_ACCEPTED)
def research_eval_job(
    body: ResearchEvalRequest, request: Request, response: Response, catalogs: Catalogs
) -> Job:
    """The Research Agent evaluation suite; failed cases are results, outages fail the job."""
    chat = _chat(request, True)
    cases = [case for case in RESEARCH_CASES if case.id in body.cases]

    def work(progress: Callable[[str], None]) -> dict[str, Any]:
        with catalogs() as catalog:
            agent = ResearchAgent(chat, catalog)
            results = []
            for case in cases:
                outcome = research_case(agent, case)
                results.append(outcome.to_dict())
                progress(f"{'PASS' if outcome.passed else 'FAIL'} {case.id}")
        return {
            "passed": sum(r["passed"] for r in results),
            "total": len(results),
            "tool_use_correct": sum(r["tool_use_correct"] for r in results),
            "tokens": sum(r["tokens"] for r in results),
            "results": results,
        }

    return _start(request, response, "research-evals", work)


class CompareRequest(FrozenModel):
    cases: list[CompareCaseId] = Field(default=[case.id for case in COMPARE_CASES], min_length=1)
    systems: list[CompareSystem] = Field(default=list(SYSTEMS), min_length=1)


@router.post("/compare", response_model=Job, status_code=status.HTTP_202_ACCEPTED)
def compare_job(
    body: CompareRequest, request: Request, response: Response, catalogs: Catalogs
) -> Job:
    """Single- versus multi-agent systems on fixed tasks, scored by code.

    An LLM or PokéAPI outage stops the run but keeps the finished runs (they cost tokens).
    """
    chat = _chat(request, True)
    cases = [case for case in COMPARE_CASES if case.id in body.cases]
    systems = [system for system in SYSTEMS if system in body.systems]

    def work(progress: Callable[[str], None]) -> dict[str, Any]:
        runs = []
        aborted = None
        with catalogs() as catalog:
            for case, system in ((c, s) for c in cases for s in systems):
                try:
                    outcome = compare_case(system, case, chat, catalog)
                except (LlmAuthError, LlmUnavailableError, UpstreamUnavailableError) as error:
                    aborted = f"{classify(error)}: {error}"
                    progress(f"aborted: {aborted}")
                    break
                runs.append(outcome.to_dict())
                progress(f"{'PASS' if outcome.passed else 'FAIL'} {case.id} {system}")
        summary = [
            {
                "system": system,
                "passed": sum(r["passed"] for r in runs if r["system"] == system),
                "runs": sum(1 for r in runs if r["system"] == system),
                "tokens": sum(r["tokens"] for r in runs if r["system"] == system),
            }
            for system in systems
        ]
        return {"runs": runs, "summary": summary, "aborted": aborted}

    return _start(request, response, "compare", work)
