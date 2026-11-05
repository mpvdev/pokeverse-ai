"""The Pokémon Research Agent: catalog tools + structured answers + grounding check."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pokeverse.agents.answers import POKEDEX_ANSWER_SCHEMA, PokedexAnswer
from pokeverse.agents.tools import make_catalog_tools
from pokeverse.catalog import PokemonCatalog
from pokeverse.llm import Completion, LlmRequestError, OutputSchema, Tool

RESEARCH_SYSTEM_PROMPT = (
    "You are the PokéVerse Research Agent, an expert on Pokémon. "
    "Before stating any Pokémon's types or Pokédex number, look it up with get_pokemon; "
    "never answer those facts from memory. "
    "If a lookup returns an error, say which fact could not be verified. "
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
    ) -> Completion: ...


@dataclass(frozen=True, slots=True)
class ResearchResult:
    answer: PokedexAnswer
    completion: Completion

    @property
    def looked_up(self) -> frozenset[str]:
        """Canonical names returned by successful tool calls."""
        return frozenset(
            call.output["name"]
            for call in self.completion.tool_calls
            if isinstance(call.output.get("name"), str)
        )

    @property
    def ungrounded(self) -> tuple[str, ...]:
        """Pokémon the answer is about that were never confirmed by a lookup."""
        return tuple(name for name in self.answer.pokemon if name not in self.looked_up)

    def to_dict(self) -> dict[str, Any]:
        return {**self.answer.to_dict(), "ungrounded": list(self.ungrounded)}


class ResearchAgent:
    """Answers Pokémon questions from the local catalog, with typed, checkable output."""

    def __init__(self, chat: ChatModel, catalog: PokemonCatalog) -> None:
        self._chat = chat
        self._tools = make_catalog_tools(catalog)

    def ask(
        self, question: str, *, temperature: float | None = None, max_tokens: int | None = None
    ) -> ResearchResult:
        completion = self._chat.complete(
            question,
            system=RESEARCH_SYSTEM_PROMPT,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=self._tools,
            output_schema=POKEDEX_ANSWER_SCHEMA,
        )
        try:
            answer = PokedexAnswer.from_dict(completion.data or {})
        except ValueError as error:
            raise LlmRequestError(f"Model reply failed validation: {error}") from error
        return ResearchResult(answer=answer, completion=completion)
