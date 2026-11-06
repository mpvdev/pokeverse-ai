"""Facts shared between agents within one supervised request."""

from dataclasses import dataclass, field
from typing import Any

from pokeverse.llm import ToolCall

MATCHUP_KEYS = ("weak_to", "resists", "immune_to")


@dataclass
class SharedContext:
    """Verified facts, taken only from tool outputs (computed by our code), never model prose."""

    pokemon: dict[str, dict[str, Any]] = field(default_factory=dict)
    matchups: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.pokemon))

    def record(self, tool_calls: tuple[ToolCall, ...]) -> None:
        for call in tool_calls:
            output = call.output
            if "error" in output:
                continue
            if call.name == "get_pokemon":
                self._add_pokemon(output)
            elif call.name == "get_type_matchups":
                self._add_pokemon(output["pokemon"])
                self.matchups[output["pokemon"]["name"]] = {k: output[k] for k in MATCHUP_KEYS}
            elif call.name == "analyze_team":
                for member in output["team"]["members"]:
                    self._add_pokemon(member)

    def _add_pokemon(self, record: dict[str, Any]) -> None:
        self.pokemon[record["name"]] = record

    def render(self) -> str:
        """A prompt block listing the facts, or an empty string when there are none."""
        if not self.pokemon:
            return ""
        lines = [
            "Verified facts (from the PokéVerse catalog and type chart; rely on them "
            "instead of looking them up again):"
        ]
        for name in self.names:
            record = self.pokemon[name]
            line = f"- {name} (#{record['pokedex_id']}): {'/'.join(record['types'])}"
            matchups = self.matchups.get(name)
            if matchups:
                for key, label in (("weak_to", "weak to"), ("resists", "resists")):
                    if matchups[key]:
                        line += f"; {label} " + ", ".join(
                            f"{t} {m:g}x" for t, m in matchups[key].items()
                        )
                if matchups["immune_to"]:
                    line += "; immune to " + ", ".join(matchups["immune_to"])
            lines.append(line)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {"pokemon": [self.pokemon[n] for n in self.names], "matchups": self.matchups}


def with_context(task: str, context: SharedContext) -> str:
    facts = context.render()
    return f"{task}\n\n{facts}" if facts else task
