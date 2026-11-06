"""PokéVerse AI agents and the tools they use."""

from pokeverse.agents.answers import POKEDEX_ANSWER_SCHEMA, Confidence, PokedexAnswer
from pokeverse.agents.research import RESEARCH_SYSTEM_PROMPT, ResearchAgent, ResearchResult
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
    normalize_pokemon_identifier,
)

__all__ = [
    "POKEDEX_ANSWER_SCHEMA",
    "RESEARCH_SYSTEM_PROMPT",
    "TEAM_PROPOSAL_SCHEMA",
    "Confidence",
    "Delegation",
    "PokedexAnswer",
    "ResearchAgent",
    "ResearchResult",
    "Supervisor",
    "SupervisorResult",
    "TeamBuildResult",
    "TeamCompositionAgent",
    "TeamProposal",
    "make_catalog_tools",
    "make_team_tools",
    "normalize_pokemon_identifier",
]
