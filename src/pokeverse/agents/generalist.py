"""A single generalist agent: the baseline for the multi-agent comparison."""

from typing import Any

from pydantic import Field, InstanceOf

from pokeverse.agents.research import ChatModel
from pokeverse.agents.tools import make_catalog_tools, make_team_tools
from pokeverse.catalog import PokemonCatalog
from pokeverse.catalog.models import Slug
from pokeverse.llm import Completion, OutputSchema, parse_reply
from pokeverse.model import FrozenModel, NonBlank
from pokeverse.teams import MAX_TEAM_SIZE

GENERALIST_SYSTEM_PROMPT = (
    "You are the PokéVerse assistant, working alone. You answer Pokémon questions and build "
    "teams. Look up types with get_pokemon and type effectiveness with get_type_matchups; never "
    "answer these from memory. When asked for a team, build it, check it with analyze_team "
    "(it looks up members itself), swap members to remove vulnerabilities where the request "
    "allows, and analyze again before answering. Put the final team's canonical names in "
    "`team` (empty if no team was requested) and name every member in `answer`. "
    "Answer concisely."
)
GENERALIST_MAX_TOOL_ROUNDS = 8
GENERALIST_MAX_TOKENS = 3000


class GeneralistReply(FrozenModel):
    answer: NonBlank
    team: tuple[Slug, ...] = Field(
        max_length=MAX_TEAM_SIZE,
        description="Canonical names of the final team; empty if none was requested.",
    )


GENERALIST_SCHEMA = OutputSchema.from_model("generalist_answer", GeneralistReply)


class GeneralistResult(FrozenModel):
    answer: str
    team: tuple[str, ...]
    completion: InstanceOf[Completion] = Field(exclude=True)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class GeneralistAgent:
    """One agent with every tool; no delegation, no separate optimizer."""

    def __init__(self, chat: ChatModel, catalog: PokemonCatalog) -> None:
        self._chat = chat
        self._tools = make_catalog_tools(catalog) + make_team_tools(catalog)

    def run(self, request: str) -> GeneralistResult:
        completion = self._chat.complete(
            request,
            system=GENERALIST_SYSTEM_PROMPT,
            max_tokens=GENERALIST_MAX_TOKENS,
            tools=self._tools,
            output_schema=GENERALIST_SCHEMA,
            max_tool_rounds=GENERALIST_MAX_TOOL_ROUNDS,
        )
        reply = parse_reply(GeneralistReply, completion)
        return GeneralistResult(answer=reply.answer, team=reply.team, completion=completion)
