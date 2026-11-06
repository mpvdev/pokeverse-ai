"""A single generalist agent: the baseline for the multi-agent comparison."""

from dataclasses import dataclass
from typing import Any

from pokeverse.agents.research import ChatModel
from pokeverse.agents.tools import make_catalog_tools, make_team_tools
from pokeverse.catalog import PokemonCatalog
from pokeverse.catalog.models import NAME_PATTERN
from pokeverse.llm import Completion, LlmRequestError, OutputSchema
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

GENERALIST_SCHEMA = OutputSchema(
    name="generalist_answer",
    schema={
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "team": {
                "type": "array",
                "maxItems": MAX_TEAM_SIZE,
                "items": {"type": "string", "pattern": f"^{NAME_PATTERN.pattern}$"},
                "description": "Canonical names of the final team; empty if none was requested.",
            },
        },
        "required": ["answer", "team"],
        "additionalProperties": False,
    },
)


@dataclass(frozen=True, slots=True)
class GeneralistResult:
    answer: str
    team: tuple[str, ...]
    completion: Completion

    def to_dict(self) -> dict[str, Any]:
        return {"answer": self.answer, "team": list(self.team)}


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
        data = completion.data or {}
        answer, team = data.get("answer"), data.get("team")
        if not isinstance(answer, str) or not answer.strip() or not isinstance(team, list):
            raise LlmRequestError("Model reply failed validation", completion=completion)
        return GeneralistResult(answer, tuple(team), completion)
