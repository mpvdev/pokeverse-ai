"""The Team Composition Agent: drafts a team, checks it with deterministic analysis, revises."""

from collections import Counter
from typing import Any

from pydantic import Field, InstanceOf, computed_field

from pokeverse.agents.research import ChatModel
from pokeverse.agents.tools import make_catalog_tools, make_team_tools, normalize_identifier
from pokeverse.catalog import PokemonCatalog, PokemonNotInCatalogError
from pokeverse.catalog.models import Slug
from pokeverse.llm import Completion, LlmRequestError, OutputSchema, parse_reply
from pokeverse.model import FrozenModel, NonBlank
from pokeverse.teams import MAX_TEAM_SIZE, Team, TeamAnalysis, analyze_team

TEAM_BUILDER_SYSTEM_PROMPT = (
    "You are the PokéVerse Team Composition Agent. Build a Pokémon team that satisfies the "
    "user's request. Unless the request says otherwise, propose 6 members. "
    "analyze_team looks up every member itself, returns their types and reports names it "
    "cannot find, so try candidate teams with it directly; use get_pokemon only when you need "
    "one Pokémon's types before choosing. Never assume types. "
    "Facts listed under 'Verified facts' come from the same catalog and type chart; use them "
    "instead of looking them up again. "
    "Before answering, call analyze_team on your final team. If it reports vulnerabilities, "
    "swap members to remove them where the request allows, and analyze again. "
    "Use canonical names as returned by the tools. In `summary`, explain the team's plan and "
    "any weaknesses you could not remove; do not claim coverage the analysis did not report."
)
TEAM_BUILDER_MAX_TOOL_ROUNDS = 8
# Reasoning tokens count against this limit; constrained requests need more reasoning.
TEAM_BUILDER_MAX_TOKENS = 3000


class MemberChoice(FrozenModel):
    name: Slug = Field(description="Canonical lowercase name, e.g. 'pikachu'.")
    role: NonBlank = Field(description="This member's job in the team, in a few words.")


class TeamProposal(FrozenModel):
    """A validated team proposal; built from untrusted model output with ``parse_reply``."""

    members: tuple[MemberChoice, ...] = Field(min_length=1, max_length=MAX_TEAM_SIZE)
    summary: NonBlank = Field(description="The team's plan and any weaknesses that remain.")

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


TEAM_PROPOSAL_SCHEMA = OutputSchema.from_model("team_proposal", TeamProposal)


class TeamBuildResult(FrozenModel):
    proposal: TeamProposal
    analysis: TeamAnalysis
    completion: InstanceOf[Completion] = Field(exclude=True)

    @computed_field
    @property
    def self_checked(self) -> bool:
        """Whether the agent ran analyze_team on exactly the team it proposed."""
        final = Counter(self.analysis.team.names)
        for call in self.completion.tool_calls:
            if call.name != "analyze_team" or "error" in call.output:
                continue
            checked = Counter(m["name"] for m in call.output["team"]["members"])
            if checked == final:
                return True
        return False

    def to_dict(self) -> dict[str, Any]:
        analysis = self.analysis.to_dict()
        del analysis["exposures"]
        return {**self.proposal.to_dict(), "analysis": analysis, "self_checked": self.self_checked}


class TeamCompositionAgent:
    """Builds a team from a free-text request; the final team is re-checked by our code."""

    def __init__(self, chat: ChatModel, catalog: PokemonCatalog) -> None:
        self._chat = chat
        self._catalog = catalog
        self._tools = make_catalog_tools(catalog) + make_team_tools(catalog)

    def build(self, request: str) -> TeamBuildResult:
        completion = self._chat.complete(
            request,
            system=TEAM_BUILDER_SYSTEM_PROMPT,
            max_tokens=TEAM_BUILDER_MAX_TOKENS,
            tools=self._tools,
            output_schema=TEAM_PROPOSAL_SCHEMA,
            max_tool_rounds=TEAM_BUILDER_MAX_TOOL_ROUNDS,
        )
        proposal = parse_reply(TeamProposal, completion)
        try:
            members = tuple(
                self._catalog.get(normalize_identifier(m.name)) for m in proposal.members
            )
        except PokemonNotInCatalogError as error:
            raise LlmRequestError(
                f"Agent proposed a Pokémon that does not exist: {error}", completion=completion
            ) from error
        return TeamBuildResult(
            proposal=proposal, analysis=analyze_team(Team(members=members)), completion=completion
        )
