"""Team endpoints: deterministic, type-based team analysis (no LLM)."""

from fastapi import APIRouter
from pydantic import Field

from pokeverse.api.app import Catalogs, NameOrId, invalid_input
from pokeverse.model import FrozenModel
from pokeverse.teams import MAX_TEAM_SIZE, Team, TeamAnalysis, analyze_team

router = APIRouter(tags=["teams"])


class TeamRequest(FrozenModel):
    members: list[NameOrId] = Field(
        min_length=1,
        max_length=MAX_TEAM_SIZE,
        description="Pokémon names or Pokédex ids; the same species may repeat.",
        examples=[["charizard", "blastoise", "venusaur"]],
    )


@router.post("/teams/analysis", response_model=TeamAnalysis)
def team_analysis(request: TeamRequest, catalogs: Catalogs) -> TeamAnalysis:
    """Type weaknesses, unresisted attack types and STAB coverage gaps of a team."""
    with catalogs() as catalog:
        members = tuple(catalog.get(name) for name in request.members)
    with invalid_input():
        return analyze_team(Team(members=members))
