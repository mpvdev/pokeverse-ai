"""PokéVerse AI agents and the tools they use."""

from pokeverse.agents.answers import POKEDEX_ANSWER_SCHEMA, Confidence, PokedexAnswer
from pokeverse.agents.battle_review import BattleReview, BattleReviewAgent, Lesson
from pokeverse.agents.battle_strategy import BattleDecision, BattleStrategyAgent
from pokeverse.agents.opponent_analysis import OpponentAnalysis, OpponentAnalysisAgent
from pokeverse.agents.optimizer import OptimizationResult, TeamOptimizationAgent
from pokeverse.agents.research import (
    RESEARCH_SYSTEM_PROMPT,
    ChatModel,
    ResearchAgent,
    ResearchResult,
)
from pokeverse.agents.supervisor import Delegation, Supervisor, SupervisorResult
from pokeverse.agents.team_builder import (
    TEAM_PROPOSAL_SCHEMA,
    TeamBuildResult,
    TeamCompositionAgent,
    TeamProposal,
)
from pokeverse.agents.tools import (
    make_catalog_tools,
    make_team_tools,
    normalize_identifier,
)

__all__ = [
    "POKEDEX_ANSWER_SCHEMA",
    "RESEARCH_SYSTEM_PROMPT",
    "TEAM_PROPOSAL_SCHEMA",
    "BattleDecision",
    "BattleReview",
    "BattleReviewAgent",
    "BattleStrategyAgent",
    "ChatModel",
    "Confidence",
    "Delegation",
    "Lesson",
    "OpponentAnalysis",
    "OpponentAnalysisAgent",
    "OptimizationResult",
    "PokedexAnswer",
    "ResearchAgent",
    "ResearchResult",
    "Supervisor",
    "SupervisorResult",
    "TeamBuildResult",
    "TeamCompositionAgent",
    "TeamOptimizationAgent",
    "TeamProposal",
    "make_catalog_tools",
    "make_team_tools",
    "normalize_identifier",
]
