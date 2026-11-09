"""The Pokémon Research Agent: catalog tools + structured answers + grounding check."""

from collections.abc import Sequence
from typing import Any, Protocol

from pydantic import Field, InstanceOf, computed_field

from pokeverse.agents.answers import POKEDEX_ANSWER_SCHEMA, PokedexAnswer
from pokeverse.agents.tools import make_catalog_tools
from pokeverse.catalog import PokemonCatalog
from pokeverse.llm import Completion, OutputSchema, Tool, parse_reply
from pokeverse.llm.openai import DEFAULT_MAX_TOOL_ROUNDS
from pokeverse.model import FrozenModel

RESEARCH_SYSTEM_PROMPT = (
    "You are the PokéVerse Research Agent, an expert on Pokémon. "
    "Before stating any Pokémon's types or Pokédex number, look it up with get_pokemon; "
    "never answer those facts from memory. "
    "For weaknesses, resistances, immunities or whether a move type is effective, call "
    "get_type_matchups and report its multipliers; never work out type effectiveness yourself. "
    "If a lookup returns an error, say which fact could not be verified. "
    "Facts listed under 'Verified facts' come from the same catalog and type chart; use them "
    "instead of looking them up again. "
    "In `pokemon`, list every Pokémon your answer is about, using the canonical name "
    "returned by the tool. "
    "Set confidence to 'high' only if every fact came from tool results, 'medium' if some "
    "came from general knowledge, and 'low' if you are unsure. Answer concisely."
)


class ChatModel(Protocol):
    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: Sequence[Tool] = (),
        output_schema: OutputSchema | None = None,
        max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
    ) -> Completion: ...


class ResearchResult(FrozenModel):
    answer: PokedexAnswer
    completion: InstanceOf[Completion] = Field(exclude=True)
    # Names handed over as verified facts by an earlier specialist (see SharedContext).
    verified_elsewhere: frozenset[str] = Field(default=frozenset(), exclude=True)

    @property
    def looked_up(self) -> frozenset[str]:
        """Canonical names returned by successful tool calls."""
        names = set()
        for call in self.completion.tool_calls:
            # get_pokemon returns the Pokémon itself; get_type_matchups nests it.
            record = call.output.get("pokemon", call.output)
            if isinstance(record, dict) and isinstance(record.get("name"), str):
                names.add(record["name"])
        return frozenset(names)

    @computed_field
    @property
    def ungrounded(self) -> tuple[str, ...]:
        """Pokémon the answer is about that were neither looked up nor handed over as facts."""
        grounded = self.looked_up | self.verified_elsewhere
        return tuple(name for name in self.answer.pokemon if name not in grounded)

    def to_dict(self) -> dict[str, Any]:
        return {**self.answer.to_dict(), "ungrounded": list(self.ungrounded)}


class ResearchAgent:
    """Answers Pokémon questions from the catalog, with typed, checkable output."""

    def __init__(self, chat: ChatModel, catalog: PokemonCatalog) -> None:
        self._chat = chat
        self._tools = make_catalog_tools(catalog)

    def ask(
        self,
        question: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        verified: frozenset[str] = frozenset(),
    ) -> ResearchResult:
        """Answer ``question``; ``verified`` names facts already given in the question."""
        completion = self._chat.complete(
            question,
            system=RESEARCH_SYSTEM_PROMPT,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=self._tools,
            output_schema=POKEDEX_ANSWER_SCHEMA,
        )
        answer = parse_reply(PokedexAnswer, completion)
        return ResearchResult(answer=answer, completion=completion, verified_elsewhere=verified)
