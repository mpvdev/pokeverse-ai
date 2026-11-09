"""The Team Composition Agent: drafts a team, checks it with deterministic analysis, revises."""

from collections import Counter
from dataclasses import dataclass
from typing import Any

from pokeverse.agents.research import ChatModel
from pokeverse.agents.tools import make_catalog_tools, make_team_tools, normalize_identifier
from pokeverse.catalog import PokemonCatalog, PokemonNotInCatalogError
from pokeverse.catalog.models import NAME_PATTERN
from pokeverse.llm import Completion, LlmRequestError, OutputSchema
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

TEAM_PROPOSAL_SCHEMA = OutputSchema(
    name="team_proposal",
    schema={
        "type": "object",
        "properties": {
            "members": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_TEAM_SIZE,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "pattern": f"^{NAME_PATTERN.pattern}$",
                            "description": "Canonical lowercase name, e.g. 'pikachu'.",
                        },
                        "role": {
                            "type": "string",
                            "description": "This member's job in the team, in a few words.",
                        },
                    },
                    "required": ["name", "role"],
                    "additionalProperties": False,
                },
            },
            "summary": {
                "type": "string",
                "description": "The team's plan and any weaknesses that remain.",
            },
        },
        "required": ["members", "summary"],
        "additionalProperties": False,
    },
)


@dataclass(frozen=True, slots=True)
class MemberChoice:
    name: str
    role: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not NAME_PATTERN.fullmatch(self.name):
            raise ValueError("member name must be a canonical slug")
        if not isinstance(self.role, str) or not self.role.strip():
            raise ValueError("member role must be a non-empty string")


@dataclass(frozen=True, slots=True)
class TeamProposal:
    """A validated team proposal; built from untrusted model output via ``from_dict``."""

    members: tuple[MemberChoice, ...]
    summary: str

    def __post_init__(self) -> None:
        if not isinstance(self.members, tuple) or not 1 <= len(self.members) <= MAX_TEAM_SIZE:
            raise ValueError(f"a proposal must have 1-{MAX_TEAM_SIZE} members")
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise ValueError("summary must be a non-empty string")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TeamProposal:
        try:
            members = data["members"]
            if not isinstance(members, list):
                raise ValueError("members must be a list")
            return cls(
                members=tuple(MemberChoice(m["name"], m["role"]) for m in members),
                summary=data["summary"],
            )
        except (KeyError, TypeError) as error:
            raise ValueError(f"malformed proposal: {error}") from error

    def to_dict(self) -> dict[str, Any]:
        return {
            "members": [{"name": m.name, "role": m.role} for m in self.members],
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class TeamBuildResult:
    proposal: TeamProposal
    analysis: TeamAnalysis
    completion: Completion

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
        try:
            proposal = TeamProposal.from_dict(completion.data or {})
        except ValueError as error:
            raise LlmRequestError(
                f"Model reply failed validation: {error}", completion=completion
            ) from error
        try:
            members = tuple(
                self._catalog.get(normalize_identifier(m.name)) for m in proposal.members
            )
        except PokemonNotInCatalogError as error:
            raise LlmRequestError(
                f"Agent proposed a Pokémon that does not exist: {error}", completion=completion
            ) from error
        return TeamBuildResult(proposal, analyze_team(Team(members)), completion)
